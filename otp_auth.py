"""Custom OTP authentication endpoints using Resend for email delivery."""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from services.otp_service import (
    generate_otp,
    store_otp,
    verify_otp,
    send_otp_email,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/otp", tags=["otp-auth"])


class SendOTPRequest(BaseModel):
    email: str
    login_url: str = ""


class VerifyOTPRequest(BaseModel):
    email: str
    code: str


class SendOTPResponse(BaseModel):
    success: bool
    message: str


class VerifyOTPResponse(BaseModel):
    valid: bool
    message: str


@router.post("/send", response_model=SendOTPResponse)
async def send_otp(data: SendOTPRequest):
    """Generate and send a 6-digit OTP to the provided email."""
    email = data.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email address")

    code = generate_otp()
    store_otp(email, code)

    login_url = data.login_url.strip() if data.login_url else ""
    success = await send_otp_email(email, code, login_url=login_url)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send verification email")

    return SendOTPResponse(
        success=True,
        message="認証コードを送信しました。メールをご確認ください。"
    )


@router.post("/verify", response_model=VerifyOTPResponse)
async def verify_otp_endpoint(data: VerifyOTPRequest):
    """Verify the OTP code for the given email."""
    email = data.email.strip().lower()
    code = data.code.strip()

    if not code or len(code) != 6:
        raise HTTPException(status_code=400, detail="Invalid code format")

    is_valid = verify_otp(email, code)

    if not is_valid:
        return VerifyOTPResponse(
            valid=False,
            message="認証コードが無効または期限切れです。"
        )

    return VerifyOTPResponse(
        valid=True,
        message="認証に成功しました。"
    )