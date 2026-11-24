"""Minimal GitHub REST client (urllib only). Used only in workflow steps that hold a token;
agent processes never get a token."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .common import log


class GitHubError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(f"GitHub API {status}: {message}")
        self.status = status


class GitHub:
    def __init__(self, token: str | None = None, repo: str | None = None):
        self.token = token or os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        if not self.token:
            raise SystemExit('GH_TOKEN is not set for this step')
        self.repo = repo or os.environ['GITHUB_REPOSITORY']
        self.api = os.environ.get('GITHUB_API_URL', 'https://api.github.com')

    # -- low level -------------------------------------------------------------------------------
    def request(self, method: str, path: str, body=None, accept='application/vnd.github+json'):
        url = path if path.startswith('http') else f"{self.api}{path}"
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(4):
            req = urllib.request.Request(url, data=data, method=method, headers={
                'Authorization': f'Bearer {self.token}', 'Accept': accept,
                'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'autose-workflow',
                **({'Content-Type': 'application/json'} if data else {}),
            })
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    raw = resp.read()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as e:
                msg = e.read().decode('utf-8', 'replace')[:500]
                retry = e.code >= 500 or (e.code in (403, 429) and 'rate limit' in msg.lower())
                if retry and attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise GitHubError(e.code, msg) from None
            except urllib.error.URLError as e:
                if attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise GitHubError(0, str(e)) from None

    def paginate(self, path: str):
        page = 1
        sep = '&' if '?' in path else '?'
        while True:
            items = self.request('GET', f"{path}{sep}per_page=100&page={page}") or []
            yield from items
            if len(items) < 100:
                return
            page += 1

    # -- repository / users ----------------------------------------------------------------------
    def repo_info(self):
        return self.request('GET', f"/repos/{self.repo}")

    def permission(self, user: str) -> str | None:
        """'admin' | 'maintain' | 'write' | 'triage' | 'read' | 'none', or None if the API refuses."""
        try:
            data = self.request('GET', f"/repos/{self.repo}/collaborators/{user}/permission")
            return data.get('role_name') or data.get('permission')
        except GitHubError as e:
            log(f"permission lookup for {user} failed: {e}")
            return None

    # -- issues and comments ---------------------------------------------------------------------
    def issue(self, number):
        return self.request('GET', f"/repos/{self.repo}/issues/{number}")

    def comments(self, number):
        return list(self.paginate(f"/repos/{self.repo}/issues/{number}/comments"))

    def comment(self, number, body):
        return self.request('POST', f"/repos/{self.repo}/issues/{number}/comments", {'body': body})

    def edit_comment(self, comment_id, body):
        return self.request('PATCH', f"/repos/{self.repo}/issues/comments/{comment_id}", {'body': body})

    def add_labels(self, number, labels):
        return self.request('POST', f"/repos/{self.repo}/issues/{number}/labels", {'labels': labels})

    def remove_label(self, number, label):
        try:
            self.request('DELETE', f"/repos/{self.repo}/issues/{number}/labels/{label}")
        except GitHubError as e:
            if e.status != 404:
                raise

    # -- pull requests ---------------------------------------------------------------------------
    def pr(self, number):
        return self.request('GET', f"/repos/{self.repo}/pulls/{number}")

    def find_open_pr(self, head_branch):
        owner = self.repo.split('/')[0]
        items = self.request('GET', f"/repos/{self.repo}/pulls?state=open&head={owner}:{head_branch}") or []
        return items[0] if items else None

    def create_pr(self, title, head, base, body):
        return self.request('POST', f"/repos/{self.repo}/pulls",
                            {'title': title, 'head': head, 'base': base, 'body': body,
                             'maintainer_can_modify': True})

    def update_pr(self, number, **fields):
        return self.request('PATCH', f"/repos/{self.repo}/pulls/{number}", fields)

    def create_review(self, number, commit_id, body, event='COMMENT'):
        # The bot reviews with event=COMMENT only. GitHub does not let the PR author's token approve
        # or request changes on its own PR, and a bot approval must never count towards merging.
        return self.request('POST', f"/repos/{self.repo}/pulls/{number}/reviews",
                            {'commit_id': commit_id, 'body': body, 'event': event})

    def set_status(self, sha, state, context, description, target_url):
        return self.request('POST', f"/repos/{self.repo}/statuses/{sha}",
                            {'state': state, 'context': context, 'description': description[:140],
                             'target_url': target_url})
