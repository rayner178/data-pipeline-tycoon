"""Pure domain rules for PostgreSQL execution plans (Challenge 3)."""

import re

_INDEX_SCAN_PATTERN = re.compile(
    r"\b(?:Index Scan|Index Only Scan|Bitmap Index Scan)\b",
    re.IGNORECASE,
)
_CREATE_INDEX_PATTERN = re.compile(
    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\b",
    re.IGNORECASE,
)


def plan_uses_index(plan: str) -> bool:
    """Return True when an EXPLAIN plan scans at least one index."""
    return bool(_INDEX_SCAN_PATTERN.search(plan))


def setup_creates_index(setup_sql: str) -> bool:
    """Return True when a challenge setup defines at least one index."""
    return bool(_CREATE_INDEX_PATTERN.search(setup_sql))
