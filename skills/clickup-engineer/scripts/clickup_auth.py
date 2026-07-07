#!/usr/bin/env python3
"""ClickUp API token resolution, shared by all scripts.

Resolution order:
    1. The CLICKUP_API_TOKEN environment variable (used first when set).
    2. The fallback file ~/.agents/clickup_key.txt — whose ENTIRE contents are the
       token (nothing else). Trailing whitespace/newline is stripped.

Returns None when neither source yields a token; callers handle that as the usual
"token not set" error.
"""
from __future__ import annotations

import os
from pathlib import Path

TOKEN_ENV = "CLICKUP_API_TOKEN"
TOKEN_FILE = Path.home() / ".agents" / "clickup_key.txt"


def resolve_token() -> str | None:
    """Return the ClickUp API token: env var first, then the fallback file."""
    token = os.environ.get(TOKEN_ENV)
    if token:
        return token
    try:
        text = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None
