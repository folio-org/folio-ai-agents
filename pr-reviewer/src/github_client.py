from __future__ import annotations

import logging
from typing import Any

from github import Auth, Github, GithubIntegration
from github.PullRequest import PullRequest

logger = logging.getLogger(__name__)


class GitHubClient:
    """Wrapper around PyGithub for PR review operations.

    Supports three auth modes (highest priority first):
      1. Per-request user token (from MCP caller)
      2. Shared bot token (GITHUB_TOKEN env var)
      3. GitHub App installation auth (GITHUB_APP_ID + private key + installation ID)
    """

    def __init__(
        self,
        token: str | None = None,
        app_id: str | None = None,
        app_private_key: str | None = None,
        app_installation_id: str | None = None,
    ):
        self._token = token
        self._app_id = app_id
        self._app_private_key = app_private_key
        self._app_installation_id = app_installation_id

    def _get_client(self, user_token: str | None = None) -> Github:
        """Return an authenticated Github client.

        Priority:
          1. ``user_token`` passed per-request (from MCP caller)
          2. ``self._token`` from env var (shared bot token)
          3. GitHub App installation auth (requires app_id + private_key + installation_id)
          4. GitHub App-level client (limited — fallback)
        """
        # Highest priority: caller-supplied token
        if user_token:
            return Github(auth=Auth.Token(user_token))

        # Second priority: shared bot token from env
        if self._token:
            return Github(auth=Auth.Token(self._token))

        # Third priority: GitHub App installation auth
        if self._app_id and self._app_private_key and self._app_installation_id:
            auth = Auth.AppAuth(self._app_id, self._app_private_key)
            # PyGithub >= 2.x: use keyword arg `auth=` — passing AppAuth positionally
            # triggers AssertionError because position 0 expects integration_id (int|str).
            integration = GithubIntegration(auth=auth)
            return integration.get_github_for_installation(
                int(self._app_installation_id)
            )

        # Fallback: app-level client (read-only, no user context)
        if self._app_id and self._app_private_key:
            auth = Auth.AppAuth(self._app_id, self._app_private_key)
            integration = GithubIntegration(auth=auth)
            return integration.get_github_for_app()

        raise ValueError(
            "No GitHub credentials available. "
            "Provide a token or configure GITHUB_TOKEN / GITHUB_APP_* (with INSTALLATION_ID)."
        )

    # ── PR basics ────────────────────────────────────────────────────

    def get_pr(
        self, owner: str, repo: str, pr_number: int, token: str | None = None
    ) -> PullRequest:
        """Fetch a pull request object."""
        gh = self._get_client(token)
        return gh.get_repo(f"{owner}/{repo}").get_pull(pr_number)

    def get_pr_diff(
        self, owner: str, repo: str, pr_number: int, token: str | None = None
    ) -> str:
        """Return a unified-diff-style string for the pull request.

        PyGithub ≥ 2.x dropped the ``get_diff()`` helper on PullRequest.
        The diff is reconstructed from the per-file patches returned by
        ``get_files()`` (REST API: GET /repos/{owner}/{repo}/pulls/{pr}/files).
        The output format matches what ``_extract_diff_hunk`` expects:
        each file section starts with ``diff --git``, ``--- a/``, ``+++ b/``.
        """
        pr = self.get_pr(owner, repo, pr_number, token)
        parts: list[str] = []
        for f in pr.get_files():
            parts.append(f"diff --git a/{f.filename} b/{f.filename}")
            if f.patch:
                parts.append(f"--- a/{f.filename}")
                parts.append(f"+++ b/{f.filename}")
                parts.append(f.patch)
            else:
                parts.append("(binary or truncated — no patch available)")
        return "\n".join(parts)

    def get_pr_files(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        token: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get list of changed files in a PR with patch."""
        pr = self.get_pr(owner, repo, pr_number, token)
        files = []
        for f in pr.get_files():
            files.append(
                {
                    "filename": f.filename,
                    "status": f.status,
                    "additions": f.additions,
                    "deletions": f.deletions,
                    "changes": f.changes,
                    "patch": f.patch,
                    "contents_url": f.contents_url,
                    "sha": f.sha,
                }
            )
        return files

    def get_pr_info(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        token: str | None = None,
    ) -> dict[str, Any]:
        """Get PR metadata."""
        pr = self.get_pr(owner, repo, pr_number, token)
        return {
            "title": pr.title,
            "body": pr.body,
            "state": pr.state,
            "user": pr.user.login if pr.user else None,
            "base_branch": pr.base.ref if pr.base else None,
            "head_branch": pr.head.ref if pr.head else None,
            "base_sha": pr.base.sha if pr.base else None,
            "head_sha": pr.head.sha if pr.head else None,
            "created_at": pr.created_at.isoformat() if pr.created_at else None,
            "updated_at": pr.updated_at.isoformat() if pr.updated_at else None,
            "labels": [l.name for l in pr.get_labels()],
            "draft": pr.draft,
        }

    # ── Posting reviews ──────────────────────────────────────────────

    def post_pr_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        event: str = "COMMENT",
        token: str | None = None,
    ) -> None:
        """Post a pull request review (approve/comment/request changes)."""
        pr = self.get_pr(owner, repo, pr_number, token)
        pr.create_review(body=body, event=event)

    def post_issue_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        token: str | None = None,
    ) -> None:
        """Post a comment on a PR (as issue comment)."""
        gh = self._get_client(token)
        issue = gh.get_repo(f"{owner}/{repo}").get_issue(pr_number)
        issue.create_comment(body)

    # ── PR review comments (inline) ──────────────────────────────────

    def get_pr_review_comments(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        token: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all inline review comments on a PR."""
        pr = self.get_pr(owner, repo, pr_number, token)
        comments = []
        for c in pr.get_review_comments():
            comments.append(self._serialize_review_comment(c))
        return comments

    def get_pr_review_comment(
        self,
        owner: str,
        repo: str,
        comment_id: int,
        token: str | None = None,
    ) -> dict[str, Any]:
        """Get a single review comment by ID."""
        gh = self._get_client(token)
        repo_obj = gh.get_repo(f"{owner}/{repo}")
        # PyGithub: repo.get_review_comment(comment_id)
        c = repo_obj.get_review_comment(comment_id)
        return self._serialize_review_comment(c)

    def get_pr_issue_comments(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        token: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all issue-level (non-inline) comments on a PR."""
        pr = self.get_pr(owner, repo, pr_number, token)
        comments = []
        for c in pr.get_issue_comments():
            comments.append(
                {
                    "id": c.id,
                    "body": c.body,
                    "user": c.user.login if c.user else None,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
            )
        return comments

    def reply_to_review_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        comment_id: int,
        body: str,
        token: str | None = None,
    ) -> None:
        """Reply to an existing review comment thread.

        Uses ``create_review_comment_reply`` (PyGithub v2).
        Falls back to creating a new review comment with ``in_reply_to``.
        """
        pr = self.get_pr(owner, repo, pr_number, token)

        # Fetch the original comment to copy path/line context
        gh = self._get_client(token)
        repo_obj = gh.get_repo(f"{owner}/{repo}")
        original = repo_obj.get_review_comment(comment_id)

        try:
            pr.create_review_comment_reply(comment_id, body)
        except AttributeError:
            # Fallback for older PyGithub
            pr.create_review_comment(
                body=body,
                commit_id=original.commit_id,
                path=original.path,
                line=original.line or original.original_line,
                in_reply_to=comment_id,
            )

    def create_review_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        commit_id: str,
        path: str,
        line: int,
        token: str | None = None,
    ) -> None:
        """Create a new inline review comment on a PR."""
        pr = self.get_pr(owner, repo, pr_number, token)
        pr.create_review_comment(
            body=body,
            commit_id=commit_id,
            path=path,
            line=line,
        )

    # ── Helpers ──────────────────────────────────────────────────────

    def get_file_content_at_ref(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str,
        token: str | None = None,
    ) -> str | None:
        """Get the content of a file at a specific ref (branch/commit)."""
        try:
            gh = self._get_client(token)
            content = gh.get_repo(f"{owner}/{repo}").get_contents(path, ref=ref)
            if content and content.decoded_content:
                return content.decoded_content.decode("utf-8")
        except Exception:
            logger.warning("Could not fetch file %s at ref %s", path, ref)
        return None

    def _serialize_review_comment(self, c: Any) -> dict[str, Any]:
        """Serialize a PyGithub PullRequestComment to a dict."""
        return {
            "id": c.id,
            "body": c.body,
            "path": c.path,
            "line": c.line,
            "original_line": c.original_line,
            "commit_id": c.commit_id,
            "original_commit_id": c.original_commit_id,
            "user": c.user.login if c.user else None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "in_reply_to_id": c.in_reply_to_id,
        }
