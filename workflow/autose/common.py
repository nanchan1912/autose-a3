"""Small helpers shared by all commands: logging, subprocesses, JSON files, GitHub Actions outputs."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path


def log(msg: str) -> None:
    print(f"[autose] {msg}", file=sys.stderr, flush=True)


def run(cmd: list[str], cwd: str | Path | None = None, timeout: int = 600,
        env: dict | None = None, input_text: str | None = None,
        merge_stderr: bool = True) -> subprocess.CompletedProcess:
    """Run a command, capture output as text, never raise on a non-zero exit code."""
    try:
        return subprocess.run(cmd, cwd=cwd, env=env, input=input_text, text=True, encoding='utf-8',
                              errors='replace', stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
                              timeout=timeout)
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode('utf-8', 'replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
        return subprocess.CompletedProcess(cmd, 124, out + f"\n[autose] TIMEOUT after {timeout}s\n")


def read_json(path: str | Path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding='utf-8'))


def write_json(path: str | Path, data) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def write_text(path: str | Path, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')


def set_output(**values) -> None:
    """Write step outputs (multi-line safe). Outside Actions, print them."""
    target = os.environ.get('GITHUB_OUTPUT')
    lines = []
    for key, value in values.items():
        value = '' if value is None else str(value)
        delim = f"EOF_{uuid.uuid4().hex}"
        lines.append(f"{key}<<{delim}\n{value}\n{delim}\n")
    if target:
        with open(target, 'a', encoding='utf-8') as fh:
            fh.writelines(lines)
    else:
        for key, value in values.items():
            log(f"output {key}={value}")


def step_summary(markdown: str) -> None:
    target = os.environ.get('GITHUB_STEP_SUMMARY')
    if target:
        with open(target, 'a', encoding='utf-8') as fh:
            fh.write(markdown + '\n')


def run_url() -> str:
    server = os.environ.get('GITHUB_SERVER_URL', 'https://github.com')
    repo = os.environ.get('GITHUB_REPOSITORY', 'local/local')
    run_id = os.environ.get('GITHUB_RUN_ID', '0')
    return f"{server}/{repo}/actions/runs/{run_id}"


def truncate(text: str, limit: int, where: str = 'middle') -> str:
    if text is None:
        return ''
    if len(text) <= limit:
        return text
    if where == 'end':
        return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"
    if where == 'start':
        return f"[truncated {len(text) - limit} chars]...\n" + text[-limit:]
    half = limit // 2
    return text[:half] + f"\n...[truncated {len(text) - limit} chars]...\n" + text[-half:]
