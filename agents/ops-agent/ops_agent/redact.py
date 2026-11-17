"""Redaction before anything reaches the model, the database or a notification (design §9.3).

Conservative on purpose: a false positive costs a little evidence, a false negative leaks a secret into Phoenix,
Postgres or the phone. Counts are returned so a spike can become a finding (something is logging secrets).
"""
from __future__ import annotations

import math
import re

_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("pem", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.S),
     "[REDACTED:private-key]"),
    ("auth-header", re.compile(r"(?i)\b(authorization|proxy-authorization|x-api-key|api-key|x-auth-token|cookie|set-cookie)"
                               r"(\"?\s*[:=]\s*+\"?)(?!\[REDACTED)([^\r\n\"]+)"), r"\1\2[REDACTED]"),
    ("bearer", re.compile(r"(?i)\b(bearer|basic|token)\s++(?!\[REDACTED)[A-Za-z0-9._~+/=-]{12,}"), r"\1 [REDACTED]"),
    ("url-cred", re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1[REDACTED]@"),
    ("kv-secret", re.compile(r"(?i)\b([A-Za-z0-9_-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
                             r"private[_-]?key|client[_-]?secret|salt)[A-Za-z0-9_-]*)(?![A-Za-z0-9_.-])(\"?\s*[:=]\s*+\"?)"
                             r"(?!\[REDACTED)([^\s\"',;&\]]{4,})"), r"\1\2[REDACTED]"),
    ("query-secret", re.compile(r"(?i)([?&](?:token|key|api_key|access_token|sig|signature|password)=)[^&\s]+"),
     r"\1[REDACTED]"),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "[REDACTED:sk]"),
    ("github-token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"), "[REDACTED:gh]"),
    ("aws-key", re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"), "[REDACTED:aws]"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[REDACTED:jwt]"),
    ("age-key", re.compile(r"\bAGE-SECRET-KEY-1[0-9A-Z]{50,}"), "[REDACTED:age]"),
    ("ntfy-topic", re.compile(r"(?i)ntfy\.sh/[A-Za-z0-9_-]{6,}"), "ntfy.sh/[REDACTED]"),
    ("ntfy-token", re.compile(r"\btk_[a-z0-9]{29}\b"), "[REDACTED:ntfy]"),
]

_TOKENISH = re.compile(r"[A-Za-z0-9+/_=-]{32,}")
_K8S_NAME = re.compile(r"^[A-Za-z]*[/a-z0-9.-]*$")
_HEX_DIGEST = re.compile(r"^(sha256:)?[a-f0-9]{40}$|^(sha256:)?[a-f0-9]{64}$")


def _entropy(s: str) -> float:
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    return -sum(c / len(s) * math.log2(c / len(s)) for c in counts.values())


def redact(text: str) -> tuple[str, int]:
    """Return (redacted text, number of redactions)."""
    if not text:
        return text, 0
    n = 0
    for _name, rx, repl in _RULES:
        text, k = rx.subn(repl, text)
        n += k

    def _hi(m: re.Match[str]) -> str:
        nonlocal n
        s = m.group(0)
        # Image digests and git SHAs are evidence, not secrets.
        if _HEX_DIGEST.match(s) or s.startswith("sha256") or "/" in s.strip("/") and s.count("/") > 2:
            return s
        # Kubernetes and host names (lowercase, digits, dashes, dots, slashes: Pod/ns/name-7d9f-x2) are evidence
        if _K8S_NAME.match(s):
            return s
        if _entropy(s) >= 4.2:
            n += 1
            return "[REDACTED:entropy]"
        return s

    text = _TOKENISH.sub(_hi, text)
    return text, n


def clean(text: str, cap: int = 12000) -> str:
    out, _ = redact(text)
    if len(out) > cap:
        out = out[:cap] + f"\n[truncated: {len(text) - cap} more characters]"
    return out
