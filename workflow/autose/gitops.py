"""Git helpers for the agents' working copy. Only the orchestrator runs git; agents have no git tool."""
from __future__ import annotations

from pathlib import Path

from .common import run

BOT_NAME = 'autose[bot]'
BOT_EMAIL = '41898282+github-actions[bot]@users.noreply.github.com'


class Repo:
    def __init__(self, path: Path):
        self.path = Path(path)

    def git(self, *args, timeout=300) -> str:
        proc = run(['git', '-c', 'core.quotepath=off', *args], cwd=self.path, timeout=timeout, merge_stderr=False)
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {(proc.stdout + (proc.stderr or ''))[-2000:]}")
        return proc.stdout

    def lines(self, *args) -> list[str]:
        return [ln for ln in self.git(*args).splitlines() if ln.strip()]

    def head(self) -> str:
        return self.git('rev-parse', 'HEAD').strip()

    def changed_since(self, rev: str) -> list[str]:
        """Files changed in the working tree (tracked or new) compared with `rev`."""
        tracked = self.lines('diff', '--name-only', rev)
        untracked = self.lines('ls-files', '--others', '--exclude-standard')
        return sorted(set(tracked) | set(untracked))

    def revert(self, paths: list[str], rev: str) -> None:
        """Undo changes to `paths`: restore tracked files from `rev`, delete new files."""
        existing = set(self.lines('ls-tree', '-r', '--name-only', rev))
        for p in paths:
            if p in existing:
                self.git('checkout', rev, '--', p)
            else:
                f = self.path / p
                if f.is_file():
                    f.unlink()

    def commit_all(self, message: str) -> str | None:
        self.git('add', '-A')
        if not self.git('status', '--porcelain').strip():
            return None
        self.git('-c', f'user.name={BOT_NAME}', '-c', f'user.email={BOT_EMAIL}', 'commit', '-q', '-m', message)
        return self.head()

    def diff(self, base: str, head: str = 'HEAD', paths: list[str] | None = None) -> str:
        return self.git('diff', f'{base}...{head}', '--', *(paths or []))

    def diff_stat(self, base: str, head: str = 'HEAD') -> str:
        return self.git('diff', '--stat', f'{base}...{head}')

    def files_between(self, base: str, head: str = 'HEAD') -> list[str]:
        return self.lines('diff', '--name-only', f'{base}...{head}')

    def show(self, rev: str, path: str) -> str | None:
        proc = run(['git', 'show', f'{rev}:{path}'], cwd=self.path, merge_stderr=False)
        return proc.stdout if proc.returncode == 0 else None
