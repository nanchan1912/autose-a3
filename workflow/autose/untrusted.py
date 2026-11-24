"""Handling of untrusted text (issue bodies, comments, PR descriptions).

Anyone can open an issue, so issue text is data, never instructions. This module
  * removes hidden content (HTML comments, zero-width and bidi control characters) that a maintainer
    would not see on the issue page but an agent would read;
  * truncates very long text;
  * flags text that looks like a prompt-injection attempt (reported, and the high-risk ones stop the run);
  * wraps the text in clearly labelled delimiters that the agent prompts refer to;
  * neutralises @mentions before any agent-written text is posted back to GitHub.
"""
from __future__ import annotations

import re

_HIDDEN_HTML = re.compile(r'<!--.*?-->', re.S)
_INVISIBLE = re.compile('[​-‏‪-‮⁠-⁤﻿]')

# (pattern, risk). "high" stops the run before any agent sees the text.
_INJECTION_PATTERNS = [
    (r'ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions|prompts?|rules)', 'high'),
    (r'disregard\s+(all\s+|the\s+)?(previous|prior|above|system)', 'high'),
    (r'\b(ANTHROPIC_API_KEY|GITHUB_TOKEN|GH_TOKEN|ACTIONS_RUNTIME_TOKEN)\b', 'high'),
    (r'\b(printenv|os\.environ|/proc/self/environ)\b', 'high'),
    (r'\b(curl|wget|nc|netcat)\s+(-\S+\s+)*https?://', 'high'),
    (r'\byou\s+are\s+now\b', 'medium'),
    (r'\b(system\s+prompt|developer\s+message)\b', 'medium'),
    (r'\b(approve|merge)\s+(this|the)\s+(pr|pull\s+request)\b', 'medium'),
    (r'\.github/workflows', 'medium'),
    (r'</?untrusted', 'medium'),
    (r'base64\s*(-d|--decode)', 'medium'),
]


def clean(text: str | None, limit: int = 12000) -> tuple[str, list[str]]:
    """Return (cleaned text, list of notes about what was removed)."""
    notes = []
    text = text or ''
    if _HIDDEN_HTML.search(text):
        notes.append('removed hidden HTML comments')
        text = _HIDDEN_HTML.sub('', text)
    if _INVISIBLE.search(text):
        notes.append('removed invisible/bidi control characters')
        text = _INVISIBLE.sub('', text)
    text = text.replace('\r\n', '\n')
    if len(text) > limit:
        notes.append(f'truncated from {len(text)} to {limit} characters')
        text = text[:limit] + '\n[...truncated by autose...]'
    return text, notes


def scan(text: str) -> list[dict]:
    hits = []
    for pattern, risk in _INJECTION_PATTERNS:
        m = re.search(pattern, text or '', re.I)
        if m:
            hits.append({'pattern': pattern, 'risk': risk, 'match': m.group(0)[:80]})
    return hits


def wrap(kind: str, text: str) -> str:
    """Delimit untrusted text. Any closing tag inside the text is defused first."""
    safe = re.sub(r'</?\s*untrusted', '[untrusted-tag-removed]', text or '', flags=re.I)
    return (f'<untrusted kind="{kind}">\n{safe}\n</untrusted>')


def no_mentions(text: str) -> str:
    """Stop agent-written text from pinging people when it is posted to GitHub."""
    return re.sub(r'(?<![\w`])@(?=[A-Za-z0-9-])', '@​', text or '')
