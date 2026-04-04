"""OTP generation, storage, and email sending via Resend."""
import os
import random
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# In-memory OTP store: {email: {"code": str, "expires_at": datetime}}
_otp_store: dict[str, dict] = {}

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
SENDER_EMAIL = "no-reply@proof-of-human.io"
SENDER_NAME = "山奥AI研究所™"
REPLY_TO = "personaassets@proton.me"
OTP_EXPIRY_MINUTES = 10


def generate_otp() -> str:
    """Generate a random 6-digit OTP code."""
    return str(random.randint(100000, 999999))


def store_otp(email: str, code: str) -> None:
    """Store OTP with expiration."""
    _otp_store[email.lower()] = {
        "code": code,
        "expires_at": datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES),
    }


def verify_otp(email: str, code: str) -> bool:
    """Verify OTP code for an email. Returns True if valid."""
    entry = _otp_store.get(email.lower())
    if not entry:
        return False
    if datetime.utcnow() > entry["expires_at"]:
        del _otp_store[email.lower()]
        return False
    if entry["code"] != code:
        return False
    # OTP is valid — remove it
    del _otp_store[email.lower()]
    return True


async def send_otp_email(email: str, code: str, login_url: str = "") -> bool:
    """Send OTP email via Resend API."""
    try:
        import resend
        from urllib.parse import urlencode
        resend.api_key = RESEND_API_KEY

        # Build the deep-link URL for "enter code" button
        login_link = ""
        if login_url:
            params = urlencode({"email": email, "step": "code"})
            login_link = f"{login_url}?{params}"

        # Conditional button HTML
        button_html = ""
        if login_link:
            button_html = f"""
                <a href="{login_link}" style="display: inline-block; background: #00F0FF; color: #000000; font-weight: bold; font-size: 14px; text-decoration: none; padding: 12px 32px; border-radius: 8px; margin-top: 16px;">
                    コードを入力する →
                </a>
                <p style="font-size: 10px; color: #666; margin-top: 8px;">
                    ボタンが機能しない場合は、以下のURLをブラウザに貼り付けてください：<br/>
                    <a href="{login_link}" style="color: #00F0FF; word-break: break-all;">{login_link}</a>
                </p>
            """

        html_body = f"""
        <div style="font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 40px 20px; background: #0a0a0f; color: #ffffff;">
            <div style="text-align: center; margin-bottom: 30px;">
                <h1 style="font-size: 20px; margin: 0; color: #00F0FF;">山奥AI研究所™</h1>
                <p style="font-size: 12px; color: #666; margin-top: 4px;">Proof of Human</p>
            </div>
            <div style="background: #111118; border: 1px solid #1e293b; border-radius: 12px; padding: 30px; text-align: center;">
                <h2 style="font-size: 16px; color: #ffffff; margin: 0 0 8px 0;">ログイン認証コード</h2>
                <p style="font-size: 13px; color: #a1a1aa; margin: 0 0 24px 0;">あなたの認証コードは以下の通りです。</p>
                <div style="font-size: 36px; font-weight: bold; letter-spacing: 8px; color: #00F0FF; background: #0a0a0f; border-radius: 8px; padding: 16px; margin: 0 0 24px 0;">
                    {code}
                </div>
                <p style="font-size: 12px; color: #666; margin: 0 0 16px 0;">
                    このコードを入力してログインを完了してください。<br/>
                    コードは{OTP_EXPIRY_MINUTES}分間有効です。
                </p>
                {button_html}
            </div>
            <div style="margin-top: 24px; padding: 16px; background: #111118; border: 1px solid #f59e0b33; border-radius: 8px;">
                <p style="font-size: 11px; color: #f59e0b; margin: 0 0 4px 0;">⚠️ プライバシー保護のお願い</p>
                <p style="font-size: 11px; color: #a1a1aa; margin: 0;">
                    人間証明のための写真は、手書きの文字だけが写るようにしてください。住所などの個人情報が写らないよう、十分にご注意ください。
                </p>
            </div>
            <p style="font-size: 10px; color: #444; text-align: center; margin-top: 20px;">
                このメールに心当たりがない場合は無視してください。
            </p>
        </div>
        """

        params = {
            "from": f"{SENDER_NAME} <{SENDER_EMAIL}>",
            "to": [email],
            "reply_to": REPLY_TO,
            "subject": "【山奥AI研究所™】ログイン認証コード",
            "html": html_body,
        }

        resend.Emails.send(params)
        logger.info(f"OTP email sent to {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send OTP email to {email}: {e}", exc_info=True)
        return False


async def send_strike_email(email: str, display_name: str) -> bool:
    """Send 7-day ban notification email when user hits 3 strikes."""
    try:
        import resend
        resend.api_key = RESEND_API_KEY

        html_body = f"""
        <div style="font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 40px 20px; background: #0a0a0f; color: #ffffff;">
            <div style="text-align: center; margin-bottom: 30px;">
                <h1 style="font-size: 20px; margin: 0; color: #00F0FF;">山奥AI研究所™</h1>
            </div>
            <div style="background: #111118; border: 1px solid #ef4444; border-radius: 12px; padding: 30px; text-align: center;">
                <div style="font-size: 48px; margin-bottom: 16px;">⚠️</div>
                <h2 style="font-size: 18px; color: #ef4444; margin: 0 0 8px 0;">【アクセス制限】</h2>
                <p style="font-size: 14px; color: #ffffff; margin: 0 0 16px 0;">
                    {display_name}さん
                </p>
                <p style="font-size: 13px; color: #a1a1aa; margin: 0 0 16px 0;">
                    3回の警告に基づき、1週間の利用停止処分となりました。
                </p>
                <p style="font-size: 12px; color: #a1a1aa; margin: 0;">
                    人間としての再登録は1週間後にお願いします。<br/>
                    誤検知の場合は管理者に連絡してください。
                </p>
            </div>
            <p style="font-size: 10px; color: #444; text-align: center; margin-top: 20px;">
                山奥AI研究所™ — 人間だけの静かな場所
            </p>
        </div>
        """

        params = {
            "from": f"{SENDER_NAME} <{SENDER_EMAIL}>",
            "to": [email],
            "reply_to": REPLY_TO,
            "subject": "【山奥AI研究所™】アカウント利用停止のお知らせ",
            "html": html_body,
        }

        resend.Emails.send(params)
        logger.info(f"Strike notification email sent to {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send strike email: {e}", exc_info=True)
        return False


async def send_welcome_email(email: str, display_name: str) -> bool:
    """Send welcome email when user gets verified."""
    try:
        import resend
        resend.api_key = RESEND_API_KEY

        html_body = f"""
        <div style="font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 40px 20px; background: #0a0a0f; color: #ffffff;">
            <div style="text-align: center; margin-bottom: 30px;">
                <h1 style="font-size: 20px; margin: 0; color: #00F0FF;">山奥AI研究所™</h1>
            </div>
            <div style="background: #111118; border: 1px solid #10b981; border-radius: 12px; padding: 30px; text-align: center;">
                <div style="font-size: 48px; margin-bottom: 16px;">✅</div>
                <h2 style="font-size: 18px; color: #10b981; margin: 0 0 8px 0;">人間認証完了</h2>
                <p style="font-size: 14px; color: #ffffff; margin: 0 0 16px 0;">
                    おめでとうございます、{display_name}さん！
                </p>
                <p style="font-size: 13px; color: #a1a1aa; margin: 0;">
                    あなたの人間認証が承認されました。コミュニティへようこそ。
                </p>
            </div>
        </div>
        """

        params = {
            "from": f"{SENDER_NAME} <{SENDER_EMAIL}>",
            "to": [email],
            "reply_to": REPLY_TO,
            "subject": "【山奥AI研究所™】人間認証が完了しました",
            "html": html_body,
        }

        resend.Emails.send(params)
        return True
    except Exception as e:
        logger.error(f"Failed to send welcome email: {e}", exc_info=True)
        return False