"""Profanity filter service for blocking toxic/offensive language.

Smart filtering: distinguishes between Social Feed (strict) and Creative Content (flexible).
- Social Feed (lounge, etc.): Hard block on NG words to keep the feed clean.
- Creative Content (writing, art, photography): Allows NG words for artistic expression.
"""

import re
from typing import Optional

# NG word list - insults, slurs, and offensive terms in multiple languages
NG_WORDS: list[str] = [
    # Japanese
    "馬鹿", "バカ", "ばか", "アホ", "あほ", "クソ", "くそ", "糞",
    "死ね", "しね", "シネ", "殺す", "ころす", "コロス",
    "キモい", "きもい", "キモ", "ゴミ", "ごみ",
    "ブス", "ぶす", "デブ", "でぶ",
    "うざい", "ウザい", "ウザ",
    "カス", "かす", "ボケ", "ぼけ",
    "クズ", "くず", "屑",
    "消えろ", "きえろ",
    "ガイジ", "がいじ",
    "チビ", "ちび",
    # English
    "stupid", "idiot", "moron", "dumb", "retard", "retarded",
    "fuck", "shit", "ass", "bitch", "bastard", "damn",
    "dick", "cock", "pussy", "whore", "slut",
    "nigger", "nigga", "faggot", "fag",
    "cunt", "twat", "wanker",
    "stfu", "gtfo", "kys",
    "trash", "loser", "pathetic",
]

# Categories where NG words are ALLOWED (creative/content categories)
CREATIVE_CATEGORIES: set[str] = {"writing", "art", "photography"}

# Categories where NG words are STRICTLY BLOCKED (social feed categories)
STRICT_CATEGORIES: set[str] = {"lounge", "all"}

# Threshold for auto-freeze: repeated profanity violations
PROFANITY_FREEZE_THRESHOLD = 3


def _normalize(text: str) -> str:
    """Normalize text for matching: lowercase, strip spaces between chars."""
    text = text.lower().strip()
    # Remove zero-width characters and common obfuscation
    text = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', text)
    return text


def is_creative_category(category: str) -> bool:
    """Check if the category is a creative/content category where NG words are allowed."""
    return category.lower() in CREATIVE_CATEGORIES


def check_profanity(text: str, category: str = "lounge") -> Optional[str]:
    """
    Check if text contains any NG words, considering the post category.

    - For creative categories (writing, art, photography): Always returns None (allowed).
    - For social feed categories (lounge, etc.): Returns the matched NG word if found.

    Returns the matched NG word if blocked, None if allowed.
    """
    # Creative content gets a pass - artistic freedom
    if is_creative_category(category):
        return None

    normalized = _normalize(text)
    for word in NG_WORDS:
        word_lower = word.lower()
        if word_lower in normalized:
            return word
    return None


def get_warning_message() -> str:
    """Return the standard warning message for profanity violations in social feed."""
    return "Toxic language detected. Please keep the feed respectful. / 有害な言葉が検出されました。フィードでは敬意ある言葉遣いをお願いします。"


def get_creative_hint() -> str:
    """Return a hint about creative categories allowing more freedom."""
    return "💡 小説・作品（Writing/Art）カテゴリでは、キャラクターの台詞や芸術的表現としてこれらの言葉を使用できます。"