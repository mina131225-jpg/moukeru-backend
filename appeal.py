"""Appeal / Dispute endpoints for frozen accounts."""
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models.user_profiles import User_profiles
from services.appeal_service import process_appeal, count_appeals_today, DAILY_APPEAL_LIMIT

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/appeal", tags=["appeal"])


class AppealRequest(BaseModel):
    email: str


@router.post("/submit")
async def submit_appeal(
    data: AppealRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit an appeal for a frozen account.
    AI will analyze the user's behavior and decide:
    - "human" (high confidence) -> provisional unfreeze
    - "bot" or "uncertain" -> keep frozen, escalate to admin
    Limited to 10 appeals per day system-wide.
    """
    try:
        email = data.email.strip().lower()

        # Verify the user exists and is frozen
        result = await db.execute(
            select(User_profiles).where(User_profiles.user_id == email)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=404, detail="プロフィールが見つかりません。")
        if profile.status != "frozen":
            raise HTTPException(
                status_code=400,
                detail="このアカウントは凍結状態ではないため、異議申し立てはできません。"
            )

        # Process the appeal
        appeal_result = await process_appeal(email, db)
        return appeal_result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Appeal submission error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_appeal_status(
    email: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get appeal status for a user: whether they can appeal, remaining slots today, etc.
    """
    try:
        email = email.strip().lower()

        profile_result = await db.execute(
            select(User_profiles).where(User_profiles.user_id == email)
        )
        profile = profile_result.scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=404, detail="プロフィールが見つかりません。")

        today_count = await count_appeals_today(db)
        remaining = max(0, DAILY_APPEAL_LIMIT - today_count)

        # Check if user has already appealed today
        from models.appeal_results import Appeal_results
        from datetime import datetime, timezone
        from sqlalchemy import func, and_
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        user_appeal_result = await db.execute(
            select(Appeal_results).where(
                and_(
                    Appeal_results.user_id == email,
                    Appeal_results.created_at >= today_start,
                )
            ).order_by(Appeal_results.id.desc()).limit(1)
        )
        user_appeal = user_appeal_result.scalar_one_or_none()

        return {
            "can_appeal": profile.status == "frozen" and remaining > 0 and user_appeal is None,
            "is_frozen": profile.status == "frozen",
            "remaining_today": remaining,
            "daily_limit": DAILY_APPEAL_LIMIT,
            "already_appealed_today": user_appeal is not None,
            "last_appeal": {
                "verdict": user_appeal.verdict,
                "confidence": user_appeal.confidence,
                "reasoning": user_appeal.reasoning,
                "created_at": user_appeal.created_at.isoformat() if user_appeal.created_at else None,
            } if user_appeal else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Appeal status error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))