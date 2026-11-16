"""Best-effort removal of common credential values from diagnostics."""

import re

_HEADERS = re.compile(r"(?i)\b(cookie|set-cookie|authorization)\s*:\s*[^\r\n]*")
_SECRETS = re.compile(r"(?i)\b(cookiefile|cookies_file|token|access_token|api_key)\s*[=:]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)")


def redact(text: str) -> str:
    """Remove common credential headers, token values, and cookie file paths."""
    text = _HEADERS.sub(lambda match: match.group(1) + ": [redacted]", text)
    return _SECRETS.sub(lambda match: match.group(0).split("=", 1)[0].split(":", 1)[0] + "=[redacted]", text)
