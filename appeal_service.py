"""
Appeal / Dispute service.
- Uses AI to scan a user's behavioral data and decide whether to provisionally lift a freeze.
- Enforces a daily cap of 10 AI-verified appeals.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models.user_profiles import User_profiles
from models.posts import Posts
from models.reports import Reports
from services.aihub import AIHubService
from schemas.aihub import GenTxtRequest, ChatMessage

logger = logging.getLogger(__name__)

DAILY_APPEAL_LIMIT = 10


async def count_appeals_today(db: AsyncSession) -> int:
    """Count how many appeals have been AI-processed today (UTC)."""
    # We track appeals via the appeal_results table
    try:
        from models.appeal_results import Appeal_results
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        result = await db.execute(
            select(func.count(Appeal_results.id)).where(
                Appeal_results.created_at >= today_start
            )
        )
        return result.scalar() or 0
    except Exception:
        return 0


async def gather_user_behavior_data(user_id: str, db: AsyncSession) -> dict:
    """Gather behavioral signals for AI analysis."""
    # 1. Post frequency & patterns
    posts_result = await db.execute(
        select(Posts)
        .where(Posts.user_id == user_id)
        .order_by(Posts.id.desc())
        .limit(50)
    )
    posts = posts_result.scalars().all()

    post_count = len(posts)
    post_times = []
    post_contents = []
    for p in posts:
        if p.created_at:
            ts = p.created_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            post_times.append(ts.isoformat())
        post_contents.append(p.content[:100] if p.content else "")

    # 2. Time gaps between posts
    time_gaps = []
    for i in range(1, len(post_times)):
        try:
            t1 = datetime.fromisoformat(post_times[i - 1])
            t2 = datetime.fromisoformat(post_times[i])
            gap_seconds = abs((t1 - t2).total_seconds())
            time_gaps.append(round(gap_seconds, 1))
        except Exception:
            pass

    # 3. Report details
    reports_result = await db.execute(
        select(Reports)
        .where(Reports.reported_user_id == user_id)
        .order_by(Reports.id.desc())
        .limit(20)
    )
    reports = reports_result.scalars().all()
    report_reasons = [r.reason for r in reports if r.reason]

    # 4. Profile info
    profile_result = await db.execute(
        select(User_profiles).where(User_profiles.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()

    account_age_days = 0
    if profile and profile.created_at:
        created = profile.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        account_age_days = (datetime.now(timezone.utc) - created).days

    return {
        "user_id": user_id,
        "display_name": profile.display_name if profile else "Unknown",
        "account_age_days": account_age_days,
        "total_posts": post_count,
        "recent_post_times": post_times[:10],
        "time_gaps_seconds": time_gaps[:10],
        "sample_contents": post_contents[:5],
        "report_count": len(reports),
        "report_reasons": report_reasons[:10],
    }


async def ai_verify_human(behavior_data: dict) -> dict:
    """
    Use AI to analyze behavioral data and determine if the user is likely human.
    Returns: {"verdict": "human" | "bot" | "uncertain", "confidence": float, "reasoning": str}
    """
    service = AIHubService()

    system_prompt = """あなたは「山奥AI研究所™」のセキュリティAIです。
ユーザーの行動データを分析し、そのアカウントが「人間」か「BOT/スパム」かを判定してください。

判定基準:
1. 投稿間隔: 人間は不規則な間隔で投稿する。BOTは極端に規則的または極端に速い。
2. 投稿内容: 人間の投稿は多様で個性がある。BOTは定型文やコピペが多い。
3. アカウント年齢: 新しすぎるアカウントは注意が必要。
4. 通報理由: 複数の異なるユーザーから同様の理由で通報されている場合は注意。

以下のJSON形式で回答してください（他のテキストは不要）:
{
  "verdict": "human" または "bot" または "uncertain",
  "confidence": 0.0〜1.0の数値,
  "reasoning": "判定理由の簡潔な説明（日本語）"
}"""

    user_prompt = f"""以下のユーザーの行動データを分析してください:

- ユーザーID: {behavior_data['user_id']}
- 表示名: {behavior_data['display_name']}
- アカウント作成からの日数: {behavior_data['account_age_days']}日
- 総投稿数: {behavior_data['total_posts']}
- 最近の投稿時刻（最新10件）: {behavior_data['recent_post_times']}
- 投稿間隔（秒、最新10件）: {behavior_data['time_gaps_seconds']}
- 投稿内容サンプル（最新5件）: {behavior_data['sample_contents']}
- 通報数: {behavior_data['report_count']}
- 通報理由: {behavior_data['report_reasons']}

このユーザーは人間ですか？BOTですか？"""

    try:
        request = GenTxtRequest(
            messages=[
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_prompt),
            ],
            model="deepseek-v3.2",
        )
        response = await service.gentxt(request)
        content = response.content.strip()

        # Parse JSON from response
        import json
        # Try to extract JSON from the response
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        result = json.loads(content)
        return {
            "verdict": result.get("verdict", "uncertain"),
            "confidence": float(result.get("confidence", 0.5)),
            "reasoning": result.get("reasoning", "判定不能"),
        }
    except Exception as e:
        logger.error(f"AI verification failed: {e}", exc_info=True)
        return {
            "verdict": "uncertain",
            "confidence": 0.0,
            "reasoning": f"AI検証中にエラーが発生しました: {str(e)[:100]}",
        }


async def process_appeal(user_id: str, db: AsyncSession) -> dict:
    """
    Process an appeal:
    1. Check daily limit
    2. Gather behavior data
    3. Run AI verification
    4. If "human" -> provisionally unfreeze
    5. If "bot" or "uncertain" -> keep frozen, add to admin review queue
    Returns result dict.
    """
    # Check daily limit
    today_count = await count_appeals_today(db)
    if today_count >= DAILY_APPEAL_LIMIT:
        return {
            "success": False,
            "verdict": "limit_reached",
            "message": f"本日のAI検証枠（{DAILY_APPEAL_LIMIT}件/日）に達しました。明日再度お試しください。",
            "remaining_today": 0,
        }

    # Get user profile
    profile_result = await db.execute(
        select(User_profiles).where(User_profiles.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        return {"success": False, "verdict": "error", "message": "プロフィールが見つかりません。"}

    if profile.status not in ("frozen",):
        return {"success": False, "verdict": "error", "message": "このアカウントは凍結状態ではありません。"}

    # Gather behavior data
    behavior_data = await gather_user_behavior_data(user_id, db)

    # AI verification
    ai_result = await ai_verify_human(behavior_data)

    # Record the appeal result
    try:
        from models.appeal_results import Appeal_results
        appeal_record = Appeal_results(
            user_id=user_id,
            verdict=ai_result["verdict"],
            confidence=ai_result["confidence"],
            reasoning=ai_result["reasoning"],
            created_at=datetime.now(timezone.utc),
        )
        db.add(appeal_record)
    except Exception as e:
        logger.error(f"Failed to record appeal: {e}")

    # Apply verdict
    if ai_result["verdict"] == "human" and ai_result["confidence"] >= 0.6:
        # Provisionally unfreeze
        profile.status = "verified"
        profile.frozen_until = None
        profile.investigation_flag = False
        profile.report_count = 0
        await db.commit()
        return {
            "success": True,
            "verdict": "human",
            "message": "AI検証の結果、人間である可能性が高いと判断されました。アカウントの仮復旧を行いました。",
            "confidence": ai_result["confidence"],
            "reasoning": ai_result["reasoning"],
            "remaining_today": DAILY_APPEAL_LIMIT - today_count - 1,
        }
    else:
        # Keep frozen, escalate to admin
        profile.investigation_flag = True
        await db.commit()
        verdict_label = "BOTの疑い" if ai_result["verdict"] == "bot" else "判定不能"
        return {
            "success": False,
            "verdict": ai_result["verdict"],
            "message": f"AI検証の結果: {verdict_label}。アカウントの停止を継続し、管理者の最終判断を待ちます。",
            "confidence": ai_result["confidence"],
            "reasoning": ai_result["reasoning"],
            "remaining_today": DAILY_APPEAL_LIMIT - today_count - 1,
        }