import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
import stripe

from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from core.config import settings

stripe.api_key = settings.stripe_secret_key

router = APIRouter(prefix="/api/v1/payment", tags=["payment"])

logger = logging.getLogger(__name__)


class CheckoutSessionRequest(BaseModel):
    plan: str  # "pro" or "enterprise"
    success_url: str
    cancel_url: str


class CheckoutSessionResponse(BaseModel):
    session_id: str
    url: str


class PaymentVerificationRequest(BaseModel):
    session_id: str


class PaymentStatusResponse(BaseModel):
    status: str
    payment_status: str


PLAN_PRICES = {
    "pro": {"name": "Pro Plan", "amount": 4900, "currency": "usd"},
    "enterprise": {"name": "Enterprise Plan", "amount": 19900, "currency": "usd"},
}


@router.post("/create_payment_session", response_model=CheckoutSessionResponse)
async def create_payment_session(
    data: CheckoutSessionRequest,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe checkout session for subscription"""
    try:
        frontend_host = request.headers.get("App-Host")
        if frontend_host and not frontend_host.startswith(("http://", "https://")):
            frontend_host = f"https://{frontend_host}"

        plan = PLAN_PRICES.get(data.plan)
        if not plan:
            raise HTTPException(status_code=400, detail="Invalid plan")

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": plan["currency"],
                        "product_data": {"name": plan["name"]},
                        "unit_amount": plan["amount"],
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=f"{frontend_host}/payment-success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{frontend_host}/pricing",
            metadata={
                "user_id": str(current_user.id),
                "plan": data.plan,
            },
        )

        return CheckoutSessionResponse(session_id=session.id, url=session.url)
    except Exception as e:
        logger.error(f"Payment session creation error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create payment session: {str(e)}")


@router.post("/verify_payment", response_model=PaymentStatusResponse)
async def verify_payment(
    data: PaymentVerificationRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify payment status"""
    try:
        session = stripe.checkout.Session.retrieve(data.session_id)
        status_mapping = {"complete": "paid", "open": "pending", "expired": "cancelled"}
        status = status_mapping.get(session.status, "pending")

        return PaymentStatusResponse(
            status=status,
            payment_status=session.payment_status or "unpaid",
        )
    except Exception as e:
        logger.error(f"Payment verification error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to verify payment: {str(e)}")