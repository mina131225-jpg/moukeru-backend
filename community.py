"""Community endpoints that use email-based auth (no platform auth required)."""
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select, func, distinct, and_
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models.user_profiles import User_profiles
from models.posts import Posts
from models.reports import Reports
from models.behavioral_flags import Behavioral_flags
from models.post_likes import Post_likes
from models.notifications import Notifications
from services.profanity_filter import (
    check_profanity,
    get_warning_message,
    get_creative_hint,
    PROFANITY_FREEZE_THRESHOLD,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/community", tags=["community"])

# ---------- Constants ----------
REPORT_THRESHOLD = 10  # Number of unique reporters to trigger auto-freeze
AUTO_FREEZE_DAYS = 7   # Duration of auto-freeze in days

# ---------- Ranking Cache ----------
# In-memory cache to avoid DB COUNT on every request.
# Cache is refreshed every RANKING_CACHE_TTL seconds.
RANKING_CACHE_TTL = 180  # 3 minutes
_ranking_cache: dict = {"data": None, "updated_at": 0.0}


# ---------- Schemas ----------

class CreatePostRequest(BaseModel):
    email: str
    content: str
    category: str = "lounge"
    file_key: Optional[str] = None
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    is_file_post: bool = False


class ReportPostRequest(BaseModel):
    email: str  # reporter's email
    reported_user_id: str
    reason: str
    post_id: Optional[int] = None


class StorageUrlRequest(BaseModel):
    email: str
    bucket_name: str
    object_key: str


# ---------- Helpers ----------

async def _get_verified_profile(email: str, db: AsyncSession) -> User_profiles:
    """Get a verified user profile by email. Raises 403 if not verified or frozen/banned."""
    email = email.strip().lower()
    result = await db.execute(
        select(User_profiles).where(User_profiles.user_id == email)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Check if auto-freeze has expired
    if profile.status == "frozen" and profile.frozen_until:
        now = datetime.now(timezone.utc)
        frozen_until = profile.frozen_until
        if frozen_until.tzinfo is None:
            frozen_until = frozen_until.replace(tzinfo=timezone.utc)
        if now >= frozen_until:
            # Auto-unfreeze: reset status and clear freeze fields
            profile.status = "verified"
            profile.frozen_until = None
            profile.investigation_flag = False
            profile.report_count = 0
            await db.commit()
            await db.refresh(profile)

    if profile.status not in ("verified",):
        raise HTTPException(
            status_code=403,
            detail=f"Account status: {profile.status}. Only verified users can perform this action."
        )
    return profile


async def _check_admin(email: str, db: AsyncSession) -> User_profiles:
    """Check if email belongs to an admin user."""
    email = email.strip().lower()
    result = await db.execute(
        select(User_profiles).where(
            User_profiles.user_id == email,
            User_profiles.is_admin == True,
        )
    )
    admin = result.scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return admin


# ---------- Routes ----------

@router.get("/posts")
async def list_posts(
    limit: int = 50,
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all posts (public, no auth required). Includes like_count for each post."""
    try:
        query = select(Posts).order_by(Posts.id.desc()).limit(limit)
        if category and category != "all":
            query = query.where(Posts.category == category)
        result = await db.execute(query)
        posts = result.scalars().all()

        # Batch fetch like counts for all posts
        post_ids = [p.id for p in posts]
        like_counts: dict[int, int] = {}
        if post_ids:
            counts_result = await db.execute(
                select(Post_likes.post_id, func.count(Post_likes.id))
                .where(Post_likes.post_id.in_(post_ids))
                .group_by(Post_likes.post_id)
            )
            like_counts = {row[0]: row[1] for row in counts_result.fetchall()}

        # Batch fetch avatar keys for all post authors
        author_ids = list(set(p.user_id for p in posts))
        avatar_keys: dict[str, str | None] = {}
        if author_ids:
            avatar_result = await db.execute(
                select(User_profiles.user_id, User_profiles.avatar_key)
                .where(User_profiles.user_id.in_(author_ids))
            )
            avatar_keys = {r[0]: r[1] for r in avatar_result.fetchall()}

        items = []
        for p in posts:
            items.append({
                "id": p.id,
                "user_id": p.user_id,
                "content": p.content,
                "category": getattr(p, "category", "lounge"),
                "author_name": getattr(p, "author_name", "Anonymous"),
                "author_avatar_key": avatar_keys.get(p.user_id),
                "file_key": getattr(p, "file_key", None),
                "file_name": getattr(p, "file_name", None),
                "file_type": getattr(p, "file_type", None),
                "is_file_post": getattr(p, "is_file_post", False),
                "like_count": like_counts.get(p.id, 0),
                "created_at": p.created_at.isoformat() if p.created_at else None,
            })
        return {"items": items, "total": len(items)}
    except Exception as e:
        logger.error(f"Error listing posts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/posts")
async def create_post(
    data: CreatePostRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new post. Requires verified email. Includes profanity filter."""
    try:
        profile = await _get_verified_profile(data.email, db)

        # --- Smart Profanity Filter ---
        # Creative categories (writing, art, photography) allow NG words for artistic expression.
        # Social feed categories (lounge, etc.) strictly block NG words.
        matched_word = check_profanity(data.content, category=data.category)
        if matched_word:
            # Log the violation as a behavioral flag
            flag = Behavioral_flags(
                user_id=profile.user_id,
                flag_type="profanity",
                details=f"Blocked NG word: {matched_word} (category: {data.category})",
                post_content_preview=data.content[:200],
                severity="warning",
                resolved=False,
                created_at=datetime.now(timezone.utc),
            )
            db.add(flag)

            # Count total profanity violations for this user
            count_result = await db.execute(
                select(func.count(Behavioral_flags.id)).where(
                    and_(
                        Behavioral_flags.user_id == profile.user_id,
                        Behavioral_flags.flag_type == "profanity",
                    )
                )
            )
            violation_count = (count_result.scalar() or 0) + 1  # +1 for current

            auto_frozen = False
            if violation_count >= PROFANITY_FREEZE_THRESHOLD and profile.status not in ("frozen", "banned"):
                profile.status = "frozen"
                profile.investigation_flag = True
                profile.frozen_until = datetime.now(timezone.utc) + timedelta(days=AUTO_FREEZE_DAYS)
                auto_frozen = True
                logger.info(
                    f"Auto-frozen user {profile.user_id} due to {violation_count} profanity violations. "
                    f"Frozen until {profile.frozen_until.isoformat()}"
                )

            await db.commit()

            detail_msg = get_warning_message()
            creative_hint = get_creative_hint()
            if auto_frozen:
                detail_msg += f" アカウントが{PROFANITY_FREEZE_THRESHOLD}回の違反により1週間凍結されました。"

            raise HTTPException(
                status_code=422,
                detail={
                    "message": detail_msg,
                    "creative_hint": creative_hint,
                    "violation_count": violation_count,
                    "threshold": PROFANITY_FREEZE_THRESHOLD,
                    "auto_frozen": auto_frozen,
                },
            )

        post = Posts(
            user_id=profile.user_id,
            content=data.content,
            category=data.category,
            author_name=profile.display_name or "Anonymous",
            created_at=datetime.now(),
        )
        # Set optional file fields if they exist on the model
        if data.file_key and hasattr(post, "file_key"):
            post.file_key = data.file_key
        if data.file_name and hasattr(post, "file_name"):
            post.file_name = data.file_name
        if data.file_type and hasattr(post, "file_type"):
            post.file_type = data.file_type
        if data.is_file_post and hasattr(post, "is_file_post"):
            post.is_file_post = data.is_file_post

        db.add(post)
        await db.commit()
        await db.refresh(post)
        return {
            "id": post.id,
            "content": post.content,
            "author_name": getattr(post, "author_name", "Anonymous"),
            "category": getattr(post, "category", "lounge"),
            "created_at": post.created_at.isoformat() if post.created_at else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating post: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/report")
async def report_post(
    data: ReportPostRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Report a user/post as suspicious (BOT/spam).
    - Prevents duplicate reports from the same reporter for the same user.
    - When 10 unique reporters are reached, sets investigation_flag and auto-freezes for 1 week.
    """
    try:
        profile = await _get_verified_profile(data.email, db)

        # Prevent self-reporting
        if profile.user_id == data.reported_user_id:
            raise HTTPException(status_code=400, detail="自分自身を通報することはできません。")

        # Check for duplicate report from same reporter
        existing_report = await db.execute(
            select(Reports).where(
                and_(
                    Reports.user_id == profile.user_id,
                    Reports.reported_user_id == data.reported_user_id,
                )
            )
        )
        if existing_report.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail="既にこのユーザーを通報済みです。同一ユーザーへの重複通報はできません。"
            )

        # Create the report
        report = Reports(
            user_id=profile.user_id,
            reported_user_id=data.reported_user_id,
            reason=data.reason,
            post_id=data.post_id,
            created_at=datetime.now(),
        )
        db.add(report)

        # Count unique reporters for this user (including the new one)
        count_result = await db.execute(
            select(func.count(distinct(Reports.user_id)))
            .where(Reports.reported_user_id == data.reported_user_id)
        )
        unique_reporters = (count_result.scalar() or 0) + 1  # +1 for the report we just added

        # Update reported user's profile
        target_result = await db.execute(
            select(User_profiles).where(User_profiles.user_id == data.reported_user_id)
        )
        target = target_result.scalar_one_or_none()

        auto_frozen = False
        if target:
            target.report_count = unique_reporters

            # Auto-freeze when threshold is reached
            if unique_reporters >= REPORT_THRESHOLD and target.status not in ("frozen", "banned"):
                target.status = "frozen"
                target.investigation_flag = True
                target.frozen_until = datetime.now(timezone.utc) + timedelta(days=AUTO_FREEZE_DAYS)
                auto_frozen = True
                logger.info(
                    f"Auto-frozen user {data.reported_user_id} with {unique_reporters} unique reporters. "
                    f"Frozen until {target.frozen_until.isoformat()}"
                )
            elif unique_reporters >= REPORT_THRESHOLD and target.status == "frozen":
                # Already frozen, just update the investigation flag
                target.investigation_flag = True

        await db.commit()
        return {
            "message": "通報を受け付けました。" + (" アカウントは自動的に凍結されました。" if auto_frozen else ""),
            "unique_reporters": unique_reporters,
            "threshold": REPORT_THRESHOLD,
            "auto_frozen": auto_frozen,
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error reporting: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/report-count/{reported_user_id}")
async def get_report_count(
    reported_user_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the number of unique reporters for a specific user (public)."""
    try:
        count_result = await db.execute(
            select(func.count(distinct(Reports.user_id)))
            .where(Reports.reported_user_id == reported_user_id)
        )
        count = count_result.scalar() or 0
        return {"reported_user_id": reported_user_id, "unique_reporters": count, "threshold": REPORT_THRESHOLD}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/my-reports")
async def get_my_reports(
    email: str,
    db: AsyncSession = Depends(get_db),
):
    """Get list of users the current user has already reported."""
    try:
        profile = await _get_verified_profile(email, db)
        result = await db.execute(
            select(Reports.reported_user_id)
            .where(Reports.user_id == profile.user_id)
            .distinct()
        )
        reported_ids = [row[0] for row in result.fetchall()]
        return {"reported_user_ids": reported_ids}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pending-users")
async def get_pending_users_community(
    email: str,
    db: AsyncSession = Depends(get_db),
):
    """List pending users for community review. Requires verified email."""
    try:
        await _get_verified_profile(email, db)

        result = await db.execute(
            select(User_profiles)
            .where(User_profiles.status == "pending")
            .order_by(User_profiles.id.desc())
        )
        profiles = result.scalars().all()
        items = []
        for p in profiles:
            items.append({
                "profile": {
                    "id": p.id,
                    "user_id": p.user_id,
                    "display_name": p.display_name,
                    "status": p.status,
                    "attempt_count": p.attempt_count,
                    "max_attempts": p.max_attempts,
                    "rejection_reason": p.rejection_reason,
                    "report_count": p.report_count,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                },
                "proof": None,
            })
        return {"items": items, "total": len(items)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching pending users: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reported-users")
async def get_reported_users_community(
    email: str,
    db: AsyncSession = Depends(get_db),
):
    """List reported users. Requires admin email."""
    try:
        await _check_admin(email, db)

        result = await db.execute(
            select(User_profiles)
            .where(User_profiles.report_count > 0)
            .order_by(User_profiles.report_count.desc())
            .limit(50)
        )
        profiles = result.scalars().all()
        items = [
            {
                "id": p.id,
                "user_id": p.user_id,
                "display_name": p.display_name,
                "status": p.status,
                "report_count": p.report_count,
                "investigation_flag": p.investigation_flag or False,
                "frozen_until": p.frozen_until.isoformat() if p.frozen_until else None,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in profiles
        ]
        return {"items": items, "total": len(items)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching reported users: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/suspended-accounts")
async def get_suspended_accounts(
    email: str,
    db: AsyncSession = Depends(get_db),
):
    """
    List auto-suspended (frozen) accounts for admin investigation.
    Shows accounts that were auto-frozen due to reaching the report threshold.
    """
    try:
        await _check_admin(email, db)

        result = await db.execute(
            select(User_profiles)
            .where(
                and_(
                    User_profiles.investigation_flag == True,
                    User_profiles.status.in_(["frozen", "banned"]),
                )
            )
            .order_by(User_profiles.report_count.desc())
            .limit(50)
        )
        profiles = result.scalars().all()

        items = []
        for p in profiles:
            # Get report details (reporters and reasons)
            reports_result = await db.execute(
                select(Reports)
                .where(Reports.reported_user_id == p.user_id)
                .order_by(Reports.id.desc())
                .limit(20)
            )
            reports = reports_result.scalars().all()

            report_details = []
            for r in reports:
                # Get reporter display name
                reporter_result = await db.execute(
                    select(User_profiles.display_name)
                    .where(User_profiles.user_id == r.user_id)
                )
                reporter_name = reporter_result.scalar() or "Unknown"
                report_details.append({
                    "reporter_name": reporter_name,
                    "reporter_id": r.user_id,
                    "reason": r.reason,
                    "post_id": r.post_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                })

            items.append({
                "id": p.id,
                "user_id": p.user_id,
                "display_name": p.display_name,
                "status": p.status,
                "report_count": p.report_count or 0,
                "investigation_flag": p.investigation_flag or False,
                "frozen_until": p.frozen_until.isoformat() if p.frozen_until else None,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "report_details": report_details,
            })

        return {"items": items, "total": len(items)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching suspended accounts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/report-logs/{user_id}")
async def get_report_logs(
    user_id: str,
    email: str,
    db: AsyncSession = Depends(get_db),
):
    """Get detailed report logs for a specific user. Admin only."""
    try:
        await _check_admin(email, db)

        result = await db.execute(
            select(Reports)
            .where(Reports.reported_user_id == user_id)
            .order_by(Reports.id.desc())
            .limit(50)
        )
        reports = result.scalars().all()

        items = []
        for r in reports:
            reporter_result = await db.execute(
                select(User_profiles.display_name)
                .where(User_profiles.user_id == r.user_id)
            )
            reporter_name = reporter_result.scalar() or "Unknown"
            items.append({
                "id": r.id,
                "reporter_id": r.user_id,
                "reporter_name": reporter_name,
                "reason": r.reason,
                "post_id": r.post_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })

        return {"items": items, "total": len(items)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching report logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/freeze-user")
async def freeze_user_community(
    email: str,
    user_profile_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Freeze a user. Admin only via email."""
    await _check_admin(email, db)

    result = await db.execute(
        select(User_profiles).where(User_profiles.id == user_profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")
    profile.status = "frozen"
    await db.commit()
    return {"message": "User frozen"}


@router.post("/unfreeze-user")
async def unfreeze_user_community(
    email: str,
    user_profile_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Unfreeze a user and clear investigation flags. Admin only via email."""
    await _check_admin(email, db)

    result = await db.execute(
        select(User_profiles).where(User_profiles.id == user_profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")
    profile.status = "verified"
    profile.investigation_flag = False
    profile.frozen_until = None
    profile.report_count = 0
    await db.commit()
    return {"message": "User unfrozen and investigation cleared"}


@router.post("/ban-user")
async def ban_user_community(
    email: str,
    user_profile_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Ban a user permanently. Admin only via email."""
    await _check_admin(email, db)

    result = await db.execute(
        select(User_profiles).where(User_profiles.id == user_profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")
    profile.status = "banned"
    profile.investigation_flag = True
    await db.commit()
    return {"message": "User banned permanently"}


# ---------- Private Like System ----------
# Likes are private: only the post author can see the count.
# Other users only know if THEY liked it, not the total.


class LikeRequest(BaseModel):
    email: str
    post_id: int


@router.post("/like")
async def like_post(
    data: LikeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Like a post. Each user can like a post only once. Sends notification to post author."""
    try:
        profile = await _get_verified_profile(data.email, db)

        # Check if already liked
        existing = await db.execute(
            select(Post_likes).where(
                and_(
                    Post_likes.user_id == profile.user_id,
                    Post_likes.post_id == data.post_id,
                )
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="既にいいね済みです。")

        like = Post_likes(
            user_id=profile.user_id,
            post_id=data.post_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(like)

        # Create notification for the post author
        post_result = await db.execute(
            select(Posts).where(Posts.id == data.post_id)
        )
        post = post_result.scalar_one_or_none()
        if post and post.user_id != profile.user_id:
            notification = Notifications(
                user_id=post.user_id,
                from_user_id=profile.user_id,
                from_user_name=profile.display_name or "Anonymous",
                type="like",
                post_id=data.post_id,
                post_preview=(post.content or "")[:80],
                is_read=False,
                created_at=datetime.now(timezone.utc),
            )
            db.add(notification)

        await db.commit()
        return {"message": "いいねしました", "liked": True}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error liking post: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/unlike")
async def unlike_post(
    data: LikeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Remove a like from a post."""
    try:
        profile = await _get_verified_profile(data.email, db)

        result = await db.execute(
            select(Post_likes).where(
                and_(
                    Post_likes.user_id == profile.user_id,
                    Post_likes.post_id == data.post_id,
                )
            )
        )
        like = result.scalar_one_or_none()
        if not like:
            raise HTTPException(status_code=404, detail="いいねが見つかりません。")

        await db.delete(like)
        await db.commit()
        return {"message": "いいねを取り消しました", "liked": False}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error unliking post: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/my-likes")
async def get_my_likes(
    email: str,
    db: AsyncSession = Depends(get_db),
):
    """Get list of post IDs the current user has liked."""
    try:
        profile = await _get_verified_profile(email, db)
        result = await db.execute(
            select(Post_likes.post_id).where(Post_likes.user_id == profile.user_id)
        )
        liked_ids = [row[0] for row in result.fetchall()]
        return {"liked_post_ids": liked_ids}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/my-post-likes")
async def get_my_post_likes(
    email: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get like counts for the current user's OWN posts only.
    This is the PRIVATE like system: only the author sees how many likes their posts received.
    Returns a dict of {post_id: like_count} for the user's posts.
    """
    try:
        profile = await _get_verified_profile(email, db)

        # Get all post IDs belonging to this user
        posts_result = await db.execute(
            select(Posts.id).where(Posts.user_id == profile.user_id)
        )
        my_post_ids = [row[0] for row in posts_result.fetchall()]

        if not my_post_ids:
            return {"post_like_counts": {}}

        # Count likes for each of the user's posts
        counts_result = await db.execute(
            select(Post_likes.post_id, func.count(Post_likes.id))
            .where(Post_likes.post_id.in_(my_post_ids))
            .group_by(Post_likes.post_id)
        )
        counts = {row[0]: row[1] for row in counts_result.fetchall()}
        return {"post_like_counts": counts}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Notifications System ----------


@router.get("/notifications")
async def get_notifications(
    email: str,
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """Get notifications for the current user."""
    try:
        profile = await _get_verified_profile(email, db)
        result = await db.execute(
            select(Notifications)
            .where(Notifications.user_id == profile.user_id)
            .order_by(Notifications.id.desc())
            .limit(limit)
        )
        notifs = result.scalars().all()
        items = []
        for n in notifs:
            items.append({
                "id": n.id,
                "type": n.type,
                "from_user_name": n.from_user_name,
                "post_id": n.post_id,
                "post_preview": n.post_preview,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            })
        return {"items": items, "total": len(items)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notifications/unread-count")
async def get_unread_count(
    email: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the count of unread notifications."""
    try:
        profile = await _get_verified_profile(email, db)
        result = await db.execute(
            select(func.count(Notifications.id)).where(
                and_(
                    Notifications.user_id == profile.user_id,
                    Notifications.is_read == False,
                )
            )
        )
        count = result.scalar() or 0
        return {"unread_count": count}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/notifications/mark-read")
async def mark_notifications_read(
    email: str,
    db: AsyncSession = Depends(get_db),
):
    """Mark all notifications as read for the current user."""
    try:
        profile = await _get_verified_profile(email, db)
        result = await db.execute(
            select(Notifications).where(
                and_(
                    Notifications.user_id == profile.user_id,
                    Notifications.is_read == False,
                )
            )
        )
        unread = result.scalars().all()
        for n in unread:
            n.is_read = True
        await db.commit()
        return {"message": "All notifications marked as read", "marked": len(unread)}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Post Ranking (Event Feature) ----------
# Cached ranking endpoint. DB query runs at most once per RANKING_CACHE_TTL.
# Excludes: frozen/banned users, spam-flagged posts (behavioral_flags with flag_type="spam").


@router.get("/ranking/top-posts")
async def get_post_ranking(
    db: AsyncSession = Depends(get_db),
):
    """
    Get top 10 users by valid post count.
    Uses in-memory cache (refreshed every 3 min) to avoid DB load.
    Excludes frozen/banned users.
    """
    global _ranking_cache

    now = time.time()
    if _ranking_cache["data"] is not None and (now - _ranking_cache["updated_at"]) < RANKING_CACHE_TTL:
        return _ranking_cache["data"]

    try:
        # Subquery: get user_ids that are frozen or banned
        excluded_statuses = ["frozen", "banned"]

        # Subquery: get user_ids with spam behavioral flags (copy-paste / speed abuse)
        spam_user_ids_q = (
            select(distinct(Behavioral_flags.user_id))
            .where(Behavioral_flags.flag_type.in_(["spam", "bot_typing", "copy_paste"]))
        )
        spam_result = await db.execute(spam_user_ids_q)
        spam_user_ids = {row[0] for row in spam_result.fetchall()}

        # Subquery: get user_ids that are frozen/banned
        excluded_users_q = (
            select(User_profiles.user_id)
            .where(User_profiles.status.in_(excluded_statuses))
        )
        excluded_result = await db.execute(excluded_users_q)
        excluded_user_ids = {row[0] for row in excluded_result.fetchall()}

        # Combine exclusions
        all_excluded = spam_user_ids | excluded_user_ids

        # Main query: count posts per user, exclude bad users, top 10
        query = (
            select(
                Posts.user_id,
                func.count(Posts.id).label("post_count"),
            )
            .group_by(Posts.user_id)
            .order_by(func.count(Posts.id).desc())
            .limit(10)
        )

        if all_excluded:
            query = query.where(Posts.user_id.notin_(all_excluded))

        result = await db.execute(query)
        rows = result.fetchall()

        # Fetch display names for ranked users
        ranked_user_ids = [row[0] for row in rows]
        display_names: dict[str, str] = {}
        if ranked_user_ids:
            names_result = await db.execute(
                select(User_profiles.user_id, User_profiles.display_name)
                .where(User_profiles.user_id.in_(ranked_user_ids))
            )
            display_names = {r[0]: r[1] or "Anonymous" for r in names_result.fetchall()}

        ranking = []
        for rank_idx, row in enumerate(rows, start=1):
            user_id = row[0]
            post_count = row[1]
            ranking.append({
                "rank": rank_idx,
                "user_id": user_id,
                "display_name": display_names.get(user_id, "Anonymous"),
                "post_count": post_count,
            })

        response = {
            "ranking": ranking,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "cache_ttl_seconds": RANKING_CACHE_TTL,
        }

        _ranking_cache["data"] = response
        _ranking_cache["updated_at"] = now

        return response
    except Exception as e:
        logger.error(f"Error fetching ranking: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Storage URL Endpoints (email-based auth, no platform auth needed) ----------


@router.post("/storage/upload-url")
async def get_upload_url(
    data: StorageUrlRequest,
    db: AsyncSession = Depends(get_db),
):
    """Get a presigned upload URL. Uses email-based auth instead of platform auth."""
    try:
        await _get_verified_profile(data.email, db)

        from services.storage import StorageService
        from schemas.storage import FileUpDownRequest

        service = StorageService()
        request = FileUpDownRequest(bucket_name=data.bucket_name, object_key=data.object_key)
        result = await service.create_upload_url(request)
        return {
            "upload_url": result.upload_url,
            "expires_at": result.expires_at,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting upload URL: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/storage/download-url")
async def get_download_url_endpoint(
    data: StorageUrlRequest,
    db: AsyncSession = Depends(get_db),
):
    """Get a presigned download URL. Uses email-based auth instead of platform auth."""
    try:
        await _get_verified_profile(data.email, db)

        from services.storage import StorageService
        from schemas.storage import FileUpDownRequest

        service = StorageService()
        request = FileUpDownRequest(bucket_name=data.bucket_name, object_key=data.object_key)
        result = await service.create_download_url(request)
        return {
            "download_url": result.download_url,
            "expires_at": result.expires_at,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting download URL: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/storage/download-url")
async def get_download_url_public(
    bucket_name: str,
    object_key: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a presigned download URL for viewing media (public, no auth required for viewing posts)."""
    try:
        from services.storage import StorageService
        from schemas.storage import FileUpDownRequest

        service = StorageService()
        request = FileUpDownRequest(bucket_name=bucket_name, object_key=object_key)
        result = await service.create_download_url(request)
        return {
            "download_url": result.download_url,
            "expires_at": result.expires_at,
        }
    except Exception as e:
        logger.error(f"Error getting download URL: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))