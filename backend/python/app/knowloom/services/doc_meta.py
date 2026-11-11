from __future__ import annotations

import re
from datetime import date

_EFFECTIVE_DATE = re.compile(
    r"自\s*(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*起施行"
)


def suggest_effective_at(text: str) -> str:
    """Return a display-safe ISO date suggestion without persisting it automatically."""
    tail = str(text or "")[-2400:]
    match = _EFFECTIVE_DATE.search(tail)
    if not match:
        return ""
    year, month, day = (int(value) for value in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""
