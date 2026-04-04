import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, distinct, case
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from models.user_profiles import User_profiles
from models.human_proofs import Human_proofs
from models.reports import Reports
from models.announcements import Announcements
from models.behavioral_flags import Behavioral_flags

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

# ---------- Hardcoded Admin User IDs ----------
ADMIN_USER_IDS: set[str] = set()


async def _get_admin_ids(db: AsyncSession) -> set[str]:
    """Fetch admin user_ids from DB (is_admin=True)."""
    global ADMIN_USER_IDS
    if ADMIN_USER_IDS:
        return ADMIN_USER_IDS
    result = await db.execute(
        select(User_profiles.user_id).where(User_profiles.is_admin == True)
    )
    ADMIN_USER_IDS = {row[0] for row in result.fetchall()}
    return ADMIN_USER_IDS


async def require_admin(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Dependency that ensures the current user is an admin."""
    admin_ids = await _get_admin_ids(db)
    if str(current_user.id) not in admin_ids:
        # Also check the profile directly in case cache is stale
        result = await db.execute(
            select(User_profiles).where(
                User_profiles.user_id == str(current_user.id),
                User_profiles.is_admin == True,
            )
        )
        profile = result.scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=403, detail="Admin access required")
        ADMIN_USER_IDS.add(str(current_user.id))
    return current_user


# ---------- Pydantic Schemas ----------
class ApproveRejectRequest(BaseModel):
    user_profile_id: int
    human_proof_id: int
    rejection_reason: Optional[str] = None


class FreezeUnfreezeRequest(BaseModel):
    user_profile_id: int


class ChangeStatusRequest(BaseModel):
    user_profile_id: int
    new_status: str  # "verified", "frozen", "banned", "pending"


class ReportUserRequest(BaseModel):
    reported_user_id: str
    reason: str
    post_id: Optional[int] = None


class AnnouncementCreateRequest(BaseModel):
    title: str
    content: str


class UserProfileOut(BaseModel):
    id: int
    user_id: str
    display_name: Optional[str] = None
    status: Optional[str] = None
    attempt_count: Optional[int] = None
    max_attempts: Optional[int] = None
    rejection_reason: Optional[str] = None
    report_count: Optional[int] = None
    is_admin: Optional[bool] = None
    subscription_plan: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PendingUserOut(BaseModel):
    profile: UserProfileOut
    proof: Optional[dict] = None


# ---------- Admin-Only Routes ----------


@router.get("/check-admin")
async def check_admin(
    current_user: UserResponse = Depends(require_admin),
):
    """Check if the current user is an admin."""
    return {"is_admin": True, "user_id": str(current_user.id)}


@router.get("/all-users")
async def get_all_users(
    current_user: UserResponse = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 50,
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
):
    """List all users with optional filtering."""
    try:
        query = select(User_profiles).order_by(User_profiles.id.desc())
        if status_filter and status_filter != "all":
            query = query.where(User_profiles.status == status_filter)
        if search:
            query = query.where(
                User_profiles.display_name.ilike(f"%{search}%")
            )
        query = query.offset(skip).limit(limit)
        result = await db.execute(query)
        profiles = result.scalars().all()

        # Get total count
        count_query = select(func.count(User_profiles.id))
        if status_filter and status_filter != "all":
            count_query = count_query.where(User_profiles.status == status_filter)
        if search:
            count_query = count_query.where(
                User_profiles.display_name.ilike(f"%{search}%")
            )
        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0

        items = [
            {
                "id": p.id,
                "user_id": p.user_id,
                "display_name": p.display_name,
                "status": p.status,
                "attempt_count": p.attempt_count,
                "max_attempts": p.max_attempts,
                "is_admin": p.is_admin,
                "report_count": p.report_count,
                "subscription_plan": p.subscription_plan,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in profiles
        ]
        return {"items": items, "total": total}
    except Exception as e:
        logger.error(f"Error fetching all users: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_admin_stats(
    current_user: UserResponse = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get platform-wide statistics for admin dashboard."""
    try:
        # Total users
        total_result = await db.execute(select(func.count(User_profiles.id)))
        total_users = total_result.scalar() or 0

        # Users by status
        status_result = await db.execute(
            select(User_profiles.status, func.count(User_profiles.id))
            .group_by(User_profiles.status)
        )
        status_counts = {row[0] or "unknown": row[1] for row in status_result.fetchall()}

        # Pending proofs
        pending_proofs_result = await db.execute(
            select(func.count(Human_proofs.id)).where(Human_proofs.status == "pending")
        )
        pending_proofs = pending_proofs_result.scalar() or 0

        # Total reports
        reports_result = await db.execute(select(func.count(Reports.id)))
        total_reports = reports_result.scalar() or 0

        # Active announcements
        ann_result = await db.execute(
            select(func.count(Announcements.id)).where(Announcements.is_active == True)
        )
        active_announcements = ann_result.scalar() or 0

        return {
            "total_users": total_users,
            "status_counts": status_counts,
            "pending_proofs": pending_proofs,
            "total_reports": total_reports,
            "active_announcements": active_announcements,
        }
    except Exception as e:
        logger.error(f"Error fetching admin stats: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/change-status")
async def change_user_status(
    data: ChangeStatusRequest,
    current_user: UserResponse = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Directly change a user's status (verify, freeze, ban, etc.)."""
    allowed = {"verified", "frozen", "banned", "pending"}
    if data.new_status not in allowed:
        raise HTTPException(status_code=400, detail=f"Status must be one of: {allowed}")
    try:
        result = await db.execute(
            select(User_profiles).where(User_profiles.id == data.user_profile_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=404, detail="User profile not found")
        old_status = profile.status
        profile.status = data.new_status
        await db.commit()
        return {"message": f"Status changed from '{old_status}' to '{data.new_status}'", "profile_id": profile.id}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pending-users")
async def get_pending_users(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all pending users with their latest human proof."""
    try:
        result = await db.execute(
            select(User_profiles)
            .where(User_profiles.status == "pending")
            .order_by(User_profiles.id.desc())
        )
        profiles = result.scalars().all()

        items = []
        for p in profiles:
            proof_result = await db.execute(
                select(Human_proofs)
                .where(Human_proofs.user_id == p.user_id)
                .where(Human_proofs.status == "pending")
                .order_by(Human_proofs.id.desc())
                .limit(1)
            )
            proof = proof_result.scalar_one_or_none()
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
                "proof": {
                    "id": proof.id,
                    "user_id": proof.user_id,
                    "image_key": proof.image_key,
                    "attempt_number": proof.attempt_number,
                    "status": proof.status,
                    "created_at": proof.created_at.isoformat() if proof.created_at else None,
                } if proof else None,
            })

        return {"items": items, "total": len(items)}
    except Exception as e:
        logger.error(f"Error fetching pending users: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approve-user")
async def approve_user(
    data: ApproveRejectRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve a pending user."""
    try:
        profile = await db.execute(
            select(User_profiles).where(User_profiles.id == data.user_profile_id)
        )
        profile = profile.scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=404, detail="User profile not found")

        profile.status = "verified"

        proof = await db.execute(
            select(Human_proofs).where(Human_proofs.id == data.human_proof_id)
        )
        proof = proof.scalar_one_or_none()
        if proof:
            proof.status = "approved"
            proof.reviewer_id = str(current_user.id)
            proof.reviewed_at = datetime.now()

        await db.commit()
        return {"message": "User approved successfully"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error approving user: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject-user")
async def reject_user(
    data: ApproveRejectRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reject a pending user with reason."""
    try:
        profile = await db.execute(
            select(User_profiles).where(User_profiles.id == data.user_profile_id)
        )
        profile = profile.scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=404, detail="User profile not found")

        profile.rejection_reason = data.rejection_reason
        current_attempts = (profile.attempt_count or 0) + 1
        profile.attempt_count = current_attempts
        max_att = profile.max_attempts or 3

        if current_attempts >= max_att:
            profile.status = "banned"
        else:
            profile.status = "pending"

        proof = await db.execute(
            select(Human_proofs).where(Human_proofs.id == data.human_proof_id)
        )
        proof = proof.scalar_one_or_none()
        if proof:
            proof.status = "rejected"
            proof.rejection_reason = data.rejection_reason
            proof.reviewer_id = str(current_user.id)
            proof.reviewed_at = datetime.now()

        await db.commit()
        return {
            "message": "User rejected",
            "attempt_count": current_attempts,
            "max_attempts": max_att,
            "status": profile.status,
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error rejecting user: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reported-users")
async def get_reported_users(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List users sorted by report count."""
    try:
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
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in profiles
        ]
        return {"items": items, "total": len(items)}
    except Exception as e:
        logger.error(f"Error fetching reported users: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/freeze-user")
async def freeze_user(
    data: FreezeUnfreezeRequest,
    current_user: UserResponse = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Freeze a user account."""
    try:
        result = await db.execute(
            select(User_profiles).where(User_profiles.id == data.user_profile_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=404, detail="User profile not found")
        profile.status = "frozen"
        await db.commit()
        return {"message": "User frozen successfully"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/unfreeze-user")
async def unfreeze_user(
    data: FreezeUnfreezeRequest,
    current_user: UserResponse = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Unfreeze a user account."""
    try:
        result = await db.execute(
            select(User_profiles).where(User_profiles.id == data.user_profile_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=404, detail="User profile not found")
        profile.status = "verified"
        await db.commit()
        return {"message": "User unfrozen successfully"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ban-user")
async def ban_user(
    data: FreezeUnfreezeRequest,
    current_user: UserResponse = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Permanently ban a user."""
    try:
        result = await db.execute(
            select(User_profiles).where(User_profiles.id == data.user_profile_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=404, detail="User profile not found")
        profile.status = "banned"
        await db.commit()
        return {"message": "User banned permanently"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/report-user")
async def report_user(
    data: ReportUserRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Report a user as suspicious. Auto-freeze if 3+ unique reporters."""
    try:
        report = Reports(
            user_id=str(current_user.id),
            reported_user_id=data.reported_user_id,
            reason=data.reason,
            post_id=data.post_id,
            created_at=datetime.now(),
        )
        db.add(report)

        count_result = await db.execute(
            select(func.count(distinct(Reports.user_id)))
            .where(Reports.reported_user_id == data.reported_user_id)
        )
        unique_reporters = count_result.scalar() or 0
        unique_reporters += 1

        profile_result = await db.execute(
            select(User_profiles).where(User_profiles.user_id == data.reported_user_id)
        )
        profile = profile_result.scalar_one_or_none()
        if profile:
            profile.report_count = unique_reporters
            if unique_reporters >= 3:
                profile.status = "frozen"

        await db.commit()
        return {"message": "Report submitted", "unique_reporters": unique_reporters}
    except Exception as e:
        await db.rollback()
        logger.error(f"Error reporting user: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create-announcement")
async def create_announcement(
    data: AnnouncementCreateRequest,
    current_user: UserResponse = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a global announcement (admin only)."""
    try:
        announcement = Announcements(
            user_id=str(current_user.id),
            title=data.title,
            content=data.content,
            is_active=True,
            created_at=datetime.now(),
        )
        db.add(announcement)
        await db.commit()
        await db.refresh(announcement)
        return {
            "message": "Announcement created",
            "id": announcement.id,
            "title": announcement.title,
        }
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating announcement: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/announcements")
async def get_announcements(
    current_user: UserResponse = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get all announcements (admin only)."""
    try:
        result = await db.execute(
            select(Announcements).order_by(Announcements.id.desc()).limit(50)
        )
        items = result.scalars().all()
        return {
            "items": [
                {
                    "id": a.id,
                    "title": a.title,
                    "content": a.content,
                    "is_active": a.is_active,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in items
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching announcements: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/toggle-announcement/{announcement_id}")
async def toggle_announcement(
    announcement_id: int,
    current_user: UserResponse = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Toggle an announcement's active status."""
    try:
        result = await db.execute(
            select(Announcements).where(Announcements.id == announcement_id)
        )
        ann = result.scalar_one_or_none()
        if not ann:
            raise HTTPException(status_code=404, detail="Announcement not found")
        ann.is_active = not ann.is_active
        await db.commit()
        return {"message": f"Announcement {'activated' if ann.is_active else 'deactivated'}", "is_active": ann.is_active}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/referral-tracker")
async def get_referral_tracker(
    current_user: UserResponse = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get referral tracking data - users sorted by verification count and activity patterns."""
    try:
        # Get all verified users with their stats
        result = await db.execute(
            select(User_profiles)
            .order_by(User_profiles.id.asc())
            .limit(100)
        )
        profiles = result.scalars().all()

        # Calculate referral-like metrics
        items = []
        for p in profiles:
            # Count how many proofs this user has reviewed (as reviewer)
            review_count_result = await db.execute(
                select(func.count(Human_proofs.id))
                .where(Human_proofs.reviewer_id == p.user_id)
            )
            reviews_done = review_count_result.scalar() or 0

            items.append({
                "id": p.id,
                "user_id": p.user_id,
                "display_name": p.display_name,
                "status": p.status,
                "reviews_done": reviews_done,
                "report_count": p.report_count or 0,
                "subscription_plan": p.subscription_plan,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "is_suspicious": (p.report_count or 0) >= 2,
            })

        # Sort by reviews_done descending
        items.sort(key=lambda x: x["reviews_done"], reverse=True)
        return {"items": items, "total": len(items)}
    except Exception as e:
        logger.error(f"Error fetching referral tracker: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Behavioral Flag Schemas ----------
class BehavioralFlagRequest(BaseModel):
    flag_type: str  # "paste_detected", "high_cpm", "uniform_cadence"
    details: str  # JSON string with metrics
    post_content_preview: Optional[str] = None
    severity: str = "medium"  # "low", "medium", "high"


class ResolveFlagRequest(BaseModel):
    flag_id: int
    action: str  # "dismiss", "warn", "ban"


# ---------- Behavioral Flag Routes ----------

@router.post("/submit-behavioral-flag")
async def submit_behavioral_flag(
    data: BehavioralFlagRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a behavioral flag detected on the frontend."""
    try:
        flag = Behavioral_flags(
            user_id=str(current_user.id),
            flag_type=data.flag_type,
            details=data.details,
            post_content_preview=data.post_content_preview,
            severity=data.severity,
            resolved=False,
            created_at=datetime.now(),
        )
        db.add(flag)

        # Count total unresolved flags (strikes) for this user
        strike_result = await db.execute(
            select(func.count(Behavioral_flags.id)).where(
                Behavioral_flags.user_id == str(current_user.id),
                Behavioral_flags.resolved == False,
            )
        )
        strike_count = (strike_result.scalar() or 0) + 1  # +1 for the one we just added

        # 3-Strike system: auto-freeze on 3rd strike
        auto_frozen = False
        if strike_count >= 3:
            profile_result = await db.execute(
                select(User_profiles).where(User_profiles.user_id == str(current_user.id))
            )
            profile = profile_result.scalar_one_or_none()
            if profile and profile.status not in ("frozen", "banned"):
                profile.status = "frozen"
                auto_frozen = True
                # Try to send penalty email
                try:
                    from services.otp_service import send_strike_email
                    await send_strike_email(current_user.email, profile.display_name or "User")
                except Exception as email_err:
                    logger.warning(f"Failed to send strike email: {email_err}")

        await db.commit()
        return {
            "message": "Behavioral flag recorded",
            "strike_count": strike_count,
            "auto_frozen": auto_frozen,
        }
    except Exception as e:
        await db.rollback()
        logger.error(f"Error submitting behavioral flag: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strike-count")
async def get_strike_count(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's strike count."""
    try:
        result = await db.execute(
            select(func.count(Behavioral_flags.id)).where(
                Behavioral_flags.user_id == str(current_user.id),
                Behavioral_flags.resolved == False,
            )
        )
        count = result.scalar() or 0
        return {"strike_count": count, "user_id": str(current_user.id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/behavioral-flags")
async def get_behavioral_flags(
    current_user: UserResponse = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    resolved_filter: Optional[str] = None,
):
    """Get all behavioral flags for admin review."""
    try:
        query = select(Behavioral_flags).order_by(Behavioral_flags.id.desc()).limit(100)
        if resolved_filter == "unresolved":
            query = query.where(Behavioral_flags.resolved == False)
        elif resolved_filter == "resolved":
            query = query.where(Behavioral_flags.resolved == True)

        result = await db.execute(query)
        flags = result.scalars().all()

        # Enrich with user display names
        items = []
        for f in flags:
            # Get display name
            profile_result = await db.execute(
                select(User_profiles.display_name).where(User_profiles.user_id == f.user_id)
            )
            display_name = profile_result.scalar() or "Unknown"

            # Get total strike count for this user
            strike_result = await db.execute(
                select(func.count(Behavioral_flags.id)).where(
                    Behavioral_flags.user_id == f.user_id,
                    Behavioral_flags.resolved == False,
                )
            )
            strike_count = strike_result.scalar() or 0

            items.append({
                "id": f.id,
                "user_id": f.user_id,
                "display_name": display_name,
                "flag_type": f.flag_type,
                "details": f.details,
                "post_content_preview": f.post_content_preview,
                "severity": f.severity,
                "resolved": f.resolved,
                "strike_count": strike_count,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            })

        return {"items": items, "total": len(items)}
    except Exception as e:
        logger.error(f"Error fetching behavioral flags: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resolve-behavioral-flag")
async def resolve_behavioral_flag(
    data: ResolveFlagRequest,
    current_user: UserResponse = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Resolve a behavioral flag (dismiss, warn, or ban the user)."""
    try:
        result = await db.execute(
            select(Behavioral_flags).where(Behavioral_flags.id == data.flag_id)
        )
        flag = result.scalar_one_or_none()
        if not flag:
            raise HTTPException(status_code=404, detail="Flag not found")

        flag.resolved = True

        if data.action in ("ban", "warn"):
            profile_result = await db.execute(
                select(User_profiles).where(User_profiles.user_id == flag.user_id)
            )
            profile = profile_result.scalar_one_or_none()
            if profile:
                if data.action == "ban":
                    profile.status = "banned"
                elif data.action == "warn":
                    # Just resolve the flag, user keeps their account
                    pass

        await db.commit()
        return {"message": f"Flag resolved with action: {data.action}", "flag_id": data.flag_id}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear-strikes")
async def clear_strikes(
    data: FreezeUnfreezeRequest,
    current_user: UserResponse = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Clear all strikes for a user (resolve all their flags)."""
    try:
        # Get user_id from profile
        profile_result = await db.execute(
            select(User_profiles).where(User_profiles.id == data.user_profile_id)
        )
        profile = profile_result.scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")

        # Resolve all unresolved flags
        flags_result = await db.execute(
            select(Behavioral_flags).where(
                Behavioral_flags.user_id == profile.user_id,
                Behavioral_flags.resolved == False,
            )
        )
        flags = flags_result.scalars().all()
        for f in flags:
            f.resolved = True

        # Unfreeze if frozen
        if profile.status == "frozen":
            profile.status = "verified"

        await db.commit()
        return {"message": f"Cleared {len(flags)} strikes for {profile.display_name}", "cleared": len(flags)}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))