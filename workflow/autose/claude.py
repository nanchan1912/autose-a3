"""Run one agent: a headless Claude Code process with a fixed tool allow list, a budget and a schema.

Every call is logged three ways: the raw stream-json event log, a readable Markdown transcript, and
one row in the ledger (tokens, cost, turns, refused tool calls). The ledger is what makes budgets
enforceable across stages, jobs and review rounds.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .common import log, read_json, run, truncate, write_json, write_text

CLAUDE_BIN = os.environ.get('AUTOSE_CLAUDE_BIN', 'claude')

# Only these environment variables reach the agent process (and therefore its Bash tool).
# In particular GITHUB_TOKEN / GH_TOKEN / ACTIONS_* are never passed on.
_ENV_KEEP = {
    'PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'TEMP', 'TMP', 'SHELL', 'USER', 'TERM',
    'ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN', 'VIRTUAL_ENV', 'pythonLocation', 'Python_ROOT_DIR', 'Python3_ROOT_DIR',
    'LD_LIBRARY_PATH', 'PKG_CONFIG_PATH',
    # Windows (only used for local smoke tests)
    'SYSTEMROOT', 'SYSTEMDRIVE', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'COMSPEC', 'PATHEXT',
    'PROGRAMDATA', 'PROGRAMFILES', 'WINDIR', 'CLAUDE_CODE_GIT_BASH_PATH',
}


def credential_summary() -> str:
    """Which model credential this step has (kind and length only, never the value)."""
    found = [f"{k} ({len(os.environ[k].strip())} chars)" for k in ('CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_API_KEY')
             if os.environ.get(k, '').strip()]
    return ', '.join(found) or 'NONE - set the CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY repository secret'


def agent_env() -> dict:
    # Empty values (a secret that is not set) are dropped so they cannot shadow the real credential.
    env = {k: v for k, v in os.environ.items() if k in _ENV_KEEP and v.strip()}
    env.update({
        'DISABLE_AUTOUPDATER': '1',
        'DISABLE_TELEMETRY': '1',
        'DISABLE_ERROR_REPORTING': '1',
        'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1',
        'PYTHONDONTWRITEBYTECODE': '1',
    })
    return env


class Ledger:
    """Token and cost book-keeping for one job, plus what earlier jobs of the same run spent."""

    def __init__(self, path: Path, job_budget: float, run_budget: float, prior_spent: float = 0.0):
        self.path = Path(path)
        self.job_budget = job_budget
        self.run_budget = run_budget
        self.prior_spent = prior_spent
        self.calls: list[dict] = read_json(self.path, {}).get('calls', []) if self.path.exists() else []

    @staticmethod
    def spent_in(paths) -> float:
        total = 0.0
        for p in paths:
            data = read_json(p, {}) or {}
            total += sum(c.get('cost_usd', 0.0) for c in data.get('calls', []))
        return total

    @property
    def job_spent(self) -> float:
        return sum(c.get('cost_usd', 0.0) for c in self.calls)

    def remaining(self) -> float:
        return min(self.job_budget - self.job_spent, self.run_budget - self.prior_spent - self.job_spent)

    def add(self, row: dict) -> None:
        self.calls.append(row)
        self.save()

    def totals(self) -> dict:
        keys = ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')
        out = {k: sum(c.get(k, 0) for c in self.calls) for k in keys}
        out['cost_usd'] = round(self.job_spent, 4)
        out['calls'] = len(self.calls)
        return out

    def save(self) -> None:
        write_json(self.path, {'calls': self.calls, 'totals': self.totals(),
                               'prior_spent_usd': round(self.prior_spent, 4)})


@dataclass
class AgentResult:
    role: str
    call_id: str
    model: str
    ok: bool
    structured: dict | None = None
    text: str = ''
    error: str = ''
    cost_usd: float = 0.0
    num_turns: int = 0
    duration_s: float = 0.0
    denials: list = field(default_factory=list)
    transcript: str = ''

    def brief(self) -> dict:
        d = asdict(self)
        d.pop('structured', None)
        d['text'] = truncate(self.text, 400, 'end')
        return d


def _transcript(events: list[dict]) -> str:
    """Readable Markdown version of the stream-json event log (tool inputs and outputs truncated)."""
    out = []
    for ev in events:
        t = ev.get('type')
        if t == 'system' and ev.get('subtype') == 'init':
            out.append(f"**session start** model=`{ev.get('model')}` tools={ev.get('tools')}\n")
        elif t in ('assistant', 'user'):
            for block in (ev.get('message', {}) or {}).get('content', []) or []:
                if not isinstance(block, dict):
                    continue
                bt = block.get('type')
                if bt == 'text' and block.get('text', '').strip():
                    out.append(f"**{t}:** {block['text'].strip()}\n")
                elif bt == 'tool_use':
                    inp = json.dumps(block.get('input', {}), ensure_ascii=False)
                    out.append(f"**tool call** `{block.get('name')}` {truncate(inp, 600, 'end')}\n")
                elif bt == 'tool_result':
                    content = block.get('content')
                    if isinstance(content, list):
                        content = '\n'.join(c.get('text', '') for c in content if isinstance(c, dict))
                    flag = ' (error)' if block.get('is_error') else ''
                    out.append(f"<details><summary>tool result{flag}</summary>\n\n```\n"
                               f"{truncate(str(content), 1500)}\n```\n</details>\n")
        elif t == 'result':
            out.append(f"**result** subtype=`{ev.get('subtype')}` turns={ev.get('num_turns')} "
                       f"cost=${ev.get('total_cost_usd', 0):.4f}\n")
    return '\n'.join(out)


def _parse_structured(result_event: dict) -> dict | None:
    if isinstance(result_event.get('structured_output'), dict):
        return result_event['structured_output']
    text = (result_event.get('result') or '').strip()
    # Fallback: the last fenced JSON block, or the whole text.
    if '```' in text:
        parts = text.split('```')
        for chunk in reversed(parts[1::2]):
            chunk = chunk[4:] if chunk.startswith('json') else chunk
            try:
                return json.loads(chunk)
            except ValueError:
                continue
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except ValueError:
        return None


def run_agent(*, role: str, role_cfg: dict, call_id: str, system_prompt: str, user_prompt: str,
              schema: dict, cwd: Path, log_dir: Path, ledger: Ledger) -> AgentResult:
    model = role_cfg['model']
    budget = min(role_cfg['budget_usd'], ledger.remaining())
    if budget < 0.10:
        log(f"{call_id}: budget exhausted (remaining ${ledger.remaining():.2f}), not starting the agent")
        return AgentResult(role, call_id, model, ok=False, error='budget exhausted before the call')

    log_dir.mkdir(parents=True, exist_ok=True)
    sys_file = log_dir / f"{call_id}.system.md"
    write_text(sys_file, system_prompt)
    write_text(log_dir / f"{call_id}.prompt.md", user_prompt)

    cmd = [CLAUDE_BIN, '-p',
           '--model', model, '--effort', role_cfg['effort'],
           '--output-format', 'stream-json', '--verbose',
           '--json-schema', json.dumps(schema),
           '--restricted', '--tools', ','.join(role_cfg['tools']),
           '--allowedTools', *role_cfg['allow'],
           '--permission-mode', 'dontAsk',
           '--strict-mcp-config', '--disable-slash-commands', '--no-session-persistence',
           '--max-turns', str(role_cfg['max_turns']),
           '--max-budget-usd', f"{budget:.2f}",
           '--append-system-prompt-file', str(sys_file.resolve())]
    log(f"{call_id}: starting {role} on {model} (budget ${budget:.2f}, cwd {cwd}, credential: {credential_summary()})")
    t0 = time.time()
    proc = run(cmd, cwd=cwd, timeout=role_cfg['timeout_s'], env=agent_env(), input_text=user_prompt)
    duration = time.time() - t0

    raw = proc.stdout or ''
    write_text(log_dir / f"{call_id}.jsonl", raw)
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith('{'):
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
    transcript_path = log_dir / f"{call_id}.transcript.md"
    write_text(transcript_path, f"# {call_id} ({role}, {model})\n\n" + _transcript(events))

    result_ev = next((e for e in reversed(events) if e.get('type') == 'result'), None)
    res = AgentResult(role, call_id, model, ok=False, duration_s=round(duration, 1),
                      transcript=str(transcript_path))
    usage = {}
    if result_ev is None:
        res.error = f"no result event (exit {proc.returncode}): {truncate(raw, 1500, 'start')}"
    else:
        usage = result_ev.get('usage') or {}
        res.cost_usd = float(result_ev.get('total_cost_usd') or 0.0)
        res.num_turns = int(result_ev.get('num_turns') or 0)
        res.text = result_ev.get('result') or ''
        res.denials = result_ev.get('permission_denials') or []
        res.structured = _parse_structured(result_ev)
        if result_ev.get('is_error') or result_ev.get('subtype') != 'success':
            res.error = f"agent ended with {result_ev.get('subtype')}: {truncate(res.text, 500, 'end')}"
        elif res.structured is None:
            res.error = 'agent did not return the required structured output'
        else:
            res.ok = True

    ledger.add({
        'call_id': call_id, 'role': role, 'model': model, 'ok': res.ok, 'error': res.error[:300],
        'cost_usd': res.cost_usd, 'num_turns': res.num_turns, 'duration_s': res.duration_s,
        'denied_tool_calls': len(res.denials),
        'input_tokens': usage.get('input_tokens', 0), 'output_tokens': usage.get('output_tokens', 0),
        'cache_creation_input_tokens': usage.get('cache_creation_input_tokens', 0),
        'cache_read_input_tokens': usage.get('cache_read_input_tokens', 0),
    })
    log(f"{call_id}: ok={res.ok} cost=${res.cost_usd:.4f} turns={res.num_turns} "
        f"denied={len(res.denials)} {res.error[:200]}")
    return res
