import re
from typing import Optional

def detect_language(text: str) -> str:
    if not text:
        return "unknown"
    zh_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en_letters = sum(1 for c in text if ('a' <= c <= 'z') or ('A' <= c <= 'Z'))
    total = len(text)
    if total == 0:
        return "unknown"
    zh_ratio = zh_chars / total
    en_ratio = en_letters / total
    if zh_ratio > 0.5:
        return "zh"
    if en_ratio > 0.5:
        return "en"
    return "mixed"

def sanitize_text(text: str, max_len: int = 4000) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len]

def parse_username(arg: str) -> Optional[str]:
    m = re.match(r"^@([A-Za-z0-9_]{5,})$", arg.strip())
    return m.group(1) if m else None

def detect_at_username(text: str) -> bool:
    return bool(re.match(r"^@([A-Za-z0-9_]{5,})", text.strip()))
