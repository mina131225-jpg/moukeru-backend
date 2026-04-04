"""Profile management endpoints that use email-based auth (no platform auth required)."""
import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from core.database import get_db
from models.user_profiles import User_profiles

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])

# Display name validation: allows alphanumeric, Japanese (hiragana, katakana, kanji, full-width),
# spaces, hyphens, underscores, dots, and common symbols. Max 30 chars.
# This regex explicitly permits Unicode ranges for Japanese text.
DISPLAY_NAME_PATTERN = re.compile(
    r'^[\w\s\-.\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uFF00-\uFFEF'
    r'\u2600-\u26FF\u2700-\u27BF\U0001F300-\U0001F9FF]+$'
)
DISPLAY_NAME_MAX_LEN = 30


def validate_display_name(name: str) -> str:
    """Validate and sanitize display name. Allows Japanese, alphanumeric, emoji, etc."""
    name = name.strip()
    if not name:
        return ""
    if len(name) > DISPLAY_NAME_MAX_LEN:
        name = name[:DISPLAY_NAME_MAX_LEN]
    # Allow any printable characters including Japanese — just block control chars
    # The regex is permissive; we mainly guard against empty/too-long names
    if not DISPLAY_NAME_PATTERN.match(name):
        # Fallback: strip only control characters, keep everything else
        name = re.sub(r'[\x00-\x1F\x7F]', '', name).strip()
    return name


class CreateProfileRequest(BaseModel):
    email: str
    display_name: str


class ProfileResponse(BaseModel):
    id: int
    user_id: str
    display_name: Optional[str] = None
    status: Optional[str] = None
    attempt_count: Optional[int] = None
    max_attempts: Optional[int] = None
    rejection_reason: Optional[str] = None
    is_admin: Optional[bool] = None
    report_count: Optional[int] = None
    subscription_plan: Optional[str] = None
    agreed_tos: Optional[bool] = None
    created_at: Optional[str] = None
    avatar_key: Optional[str] = None

    class Config:
        from_attributes = True


class UpdateAvatarRequest(BaseModel):
    email: str
    avatar_key: str


class UpdateDisplayNameRequest(BaseModel):
    email: str
    display_name: str


@router.post("/create")
async def create_profile(
    data: CreateProfileRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a user profile using email as the user_id. No platform auth required."""
    email = data.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")

    # Check if profile already exists for this email
    result = await db.execute(
        select(User_profiles).where(User_profiles.user_id == email)
    )
    existing = result.scalar_one_or_none()
    if existing:
        # Return existing profile
        return _profile_to_dict(existing)

    # Create new profile — auto-approve until community reaches critical mass
    try:
        name = validate_display_name(data.display_name) or f"Human #{hash(email) % 9999}"

        # Count existing users to determine if we should auto-approve
        count_result = await db.execute(
            select(func.count(User_profiles.id))
        )
        total_users = count_result.scalar() or 0

        # Auto-approve: first user becomes admin, all users auto-verified
        # until manual approval is re-enabled by admin
        is_first_user = total_users == 0
        initial_status = "verified"  # Auto-approve everyone for now

        profile = User_profiles(
            user_id=email,
            display_name=name,
            status=initial_status,
            attempt_count=0,
            max_attempts=3,
            is_admin=is_first_user,  # First user is auto-admin
            report_count=0,
            subscription_plan="free",
            agreed_tos=True,
            created_at=datetime.now(),
        )
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        return _profile_to_dict(profile)
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating profile: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/me")
async def get_my_profile(
    email: str,
    db: AsyncSession = Depends(get_db),
):
    """Get profile by email. No platform auth required."""
    email = email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")

    result = await db.execute(
        select(User_profiles).where(User_profiles.user_id == email)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return {"profile": None}

    return {"profile": _profile_to_dict(profile)}


@router.post("/toggle-auto-approve")
async def toggle_auto_approve(
    email: str,
    db: AsyncSession = Depends(get_db),
):
    """Admin can toggle auto-approve mode. When disabled, new users go to 'pending'."""
    email = email.strip().lower()
    # Verify caller is admin
    result = await db.execute(
        select(User_profiles).where(
            User_profiles.user_id == email,
            User_profiles.is_admin == True,
        )
    )
    admin = result.scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    # For now, this is informational — the auto-approve logic is in create_profile
    return {"message": "Auto-approve is currently enabled. All new users are auto-verified. Suspicious users are handled via the 3-strike behavioral system."}


@router.post("/make-admin")
async def make_admin(
    email: str,
    target_email: str,
    db: AsyncSession = Depends(get_db),
):
    """Promote a user to admin. Only existing admins can do this."""
    email = email.strip().lower()
    target_email = target_email.strip().lower()

    # Verify caller is admin
    result = await db.execute(
        select(User_profiles).where(
            User_profiles.user_id == email,
            User_profiles.is_admin == True,
        )
    )
    admin = result.scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    # Find target user
    target_result = await db.execute(
        select(User_profiles).where(User_profiles.user_id == target_email)
    )
    target = target_result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Target user not found")

    target.is_admin = True
    await db.commit()
    return {"message": f"{target.display_name} is now an admin", "target_email": target_email}


@router.post("/update-avatar")
async def update_avatar(
    data: UpdateAvatarRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update user's avatar_key after uploading an image to the avatars bucket."""
    email = data.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")

    result = await db.execute(
        select(User_profiles).where(User_profiles.user_id == email)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    profile.avatar_key = data.avatar_key
    await db.commit()
    await db.refresh(profile)
    return _profile_to_dict(profile)


@router.post("/update-display-name")
async def update_display_name(
    data: UpdateDisplayNameRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update user's display name."""
    email = data.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")

    result = await db.execute(
        select(User_profiles).where(User_profiles.user_id == email)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    name = validate_display_name(data.display_name)
    if not name:
        raise HTTPException(status_code=400, detail="Invalid display name")

    profile.display_name = name
    await db.commit()
    await db.refresh(profile)
    return _profile_to_dict(profile)


def _profile_to_dict(p: User_profiles) -> dict:
    return {
        "id": p.id,
        "user_id": p.user_id,
        "display_name": p.display_name,
        "status": p.status,
        "attempt_count": p.attempt_count,
        "max_attempts": p.max_attempts,
        "rejection_reason": p.rejection_reason,
        "is_admin": p.is_admin,
        "report_count": p.report_count,
        "subscription_plan": p.subscription_plan,
        "agreed_tos": p.agreed_tos,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "avatar_key": p.avatar_key,
    }