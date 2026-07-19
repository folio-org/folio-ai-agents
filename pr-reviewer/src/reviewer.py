from __future__ import annotations

import json
import logging
from typing import Any

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, SystemMessage

from src.config import get_settings
from src.github_client import GitHubClient
from src.models import (
    CodeIssue,
    CommentAnalysisResult,
    CommentSuggestion,
    ReviewResult,
    ReviewSummary,
)
from src.prompts import load_prompts
from src.token_budget import BudgetExceededError, TokenBudget

logger = logging.getLogger(__name__)


class PRReviewer:
    """LangChain AI agent for reviewing GitHub pull requests via AWS Bedrock."""

    def __init__(self, settings: Any | None = None):
        self.settings = settings or get_settings()
        self._llm: ChatBedrockConverse | None = None
        self.budget = TokenBudget(settings)
        self.github = GitHubClient(
            token=self.settings.github_token,
            app_id=self.settings.github_app_id,
            app_private_key=self.settings.github_app_private_key,
            app_installation_id=self.settings.github_app_installation_id,
        )
        # Load prompts — prefers S3, falls back to hardcoded defaults
        self._prompts = load_prompts(
            bucket=self.settings.s3_prompts_bucket,
            key=self.settings.s3_prompts_key,
        )

    def _guardrail_config(self) -> dict | None:
        """Return guardrails config dict if a guardrail ID is configured."""
        if self.settings.bedrock_guardrail_id:
            return {
                "guardrailIdentifier": self.settings.bedrock_guardrail_id,
                "guardrailVersion": (
                    self.settings.bedrock_guardrail_version or "DRAFT"
                ),
            }
        return None

    @property
    def llm(self) -> ChatBedrockConverse:
        """Lazily initialize the Bedrock LLM client."""
        if self._llm is None:
            kwargs = {
                "model": self.settings.bedrock_model_id,
                "region_name": self.settings.aws_region,
                "max_tokens": self.settings.bedrock_max_tokens,
                # Bedrock Converse rejects requests that specify both temperature
                # and top_p simultaneously — use temperature only.
                "temperature": self.settings.bedrock_temperature,
            }
            if guardrails := self._guardrail_config():
                kwargs["guardrails"] = guardrails
            self._llm = ChatBedrockConverse(**kwargs)
        return self._llm

    def _make_llm(
        self, max_tokens: int = 2048, temperature: float = 0.3
    ) -> ChatBedrockConverse:
        """Create a fresh LLM instance with custom params (for summarizer etc.)."""
        kwargs = {
            "model": self.settings.bedrock_model_id,
            "region_name": self.settings.aws_region,
            "max_tokens": max_tokens,
            # Bedrock Converse rejects requests that specify both temperature
            # and top_p simultaneously — use temperature only.
            "temperature": temperature,
        }
        if guardrails := self._guardrail_config():
            kwargs["guardrails"] = guardrails
        return ChatBedrockConverse(**kwargs)

    def _invoke_with_budget(
        self, llm_instance: ChatBedrockConverse, messages: list
    ) -> Any:
        """Invoke the LLM with budget check before and token recording after.

        Raises BudgetExceededError if the monthly budget is exhausted.
        """
        self.budget.check()
        response = llm_instance.invoke(messages)
        # Extract token usage from the AIMessage metadata
        meta = getattr(response, "usage_metadata", None) or {}
        input_tokens = meta.get("input_tokens", 0)
        output_tokens = meta.get("output_tokens", 0)
        if input_tokens or output_tokens:
            self.budget.record(input_tokens, output_tokens)
        return response

    # ── Full PR Review ───────────────────────────────────────────────

    def review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        github_token: str | None = None,
    ) -> ReviewResult:
        """Run a full PR review and return structured results."""
        logger.info("Reviewing %s/%s PR #%d", owner, repo, pr_number)

        pr_info = self.github.get_pr_info(owner, repo, pr_number, github_token)
        diff = self.github.get_pr_diff(owner, repo, pr_number, github_token)
        files = self.github.get_pr_files(owner, repo, pr_number, github_token)

        file_list = "\n".join(
            f"- {f['filename']} ({f['status']}, +{f['additions']}/-{f['deletions']})"
            for f in files
        )

        max_diff_chars = 100_000
        if len(diff) > max_diff_chars:
            logger.warning(
                "Diff too large (%d chars), truncating to %d",
                len(diff),
                max_diff_chars,
            )
            diff = diff[:max_diff_chars] + "\n... (diff truncated)"

        system_msg = SystemMessage(content=self._prompts["REVIEW_SYSTEM_PROMPT"])
        human_msg = HumanMessage(
            content=self._prompts["REVIEW_HUMAN_PROMPT"].format(
                repo=f"{owner}/{repo}",
                pr_number=pr_number,
                title=pr_info.get("title", ""),
                base_branch=pr_info.get("base_branch", ""),
                head_branch=pr_info.get("head_branch", ""),
                description=pr_info.get("body", "_No description_")
                or "_No description_",
                files=file_list,
                diff=diff,
            )
        )

        logger.debug("Invoking Bedrock LLM for PR review...")
        response = self._invoke_with_budget(self.llm, [system_msg, human_msg])
        raw_content = response.content
        logger.debug("Raw LLM response received (%d chars)", len(str(raw_content)))

        review_data = self._parse_review_response(raw_content)
        issues = [CodeIssue(**iss) for iss in review_data.get("issues", [])]
        summary_data = review_data.get("summary", {})
        summary = ReviewSummary(**summary_data)

        result = ReviewResult(
            pr_owner=owner,
            pr_repo=repo,
            pr_number=pr_number,
            pr_title=pr_info.get("title"),
            pr_description=pr_info.get("body"),
            summary=summary,
            issues=issues,
            raw_response=str(raw_content),
        )

        logger.info(
            "Review complete: score=%d, issues=%d",
            summary.score,
            summary.total_issues,
        )
        return result

    def generate_comment(
        self, result: ReviewResult, github_token: str | None = None
    ) -> str:
        """Generate a human-readable markdown comment from review results."""
        summarizer = self._make_llm()
        resp = self._invoke_with_budget(
            summarizer,
            [
                HumanMessage(
                    content=self._prompts["REVIEW_SUMMARIZE_PROMPT"].format(
                        review_json=result.model_dump_json(indent=2)
                    )
                )
            ],
        )
        return str(resp.content)

    # ── Comment / Conversation Review ────────────────────────────────

    def review_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        comment_id: int,
        github_token: str | None = None,
    ) -> CommentAnalysisResult:
        """Analyze a PR review comment and suggest changes.

        The agent:
          1. Fetches the comment and its context (file, line, surrounding code).
          2. Analyzes it using Bedrock Claude.
          3. Replies to the comment thread with a constructive response,
             optionally including a GitHub suggestion block.
        """
        logger.info(
            "Analyzing comment %d on %s/%s PR #%d",
            comment_id,
            owner,
            repo,
            pr_number,
        )

        # Fetch comment details
        comment = self.github.get_pr_review_comment(
            owner, repo, comment_id, github_token
        )
        comment_body = comment.get("body", "")
        file_path = comment.get("path", "")
        line = comment.get("line") or comment.get("original_line") or 0
        comment_author = comment.get("user", "unknown")

        # Fetch PR info and diff
        pr_info = self.github.get_pr_info(owner, repo, pr_number, github_token)
        diff = self.github.get_pr_diff(owner, repo, pr_number, github_token)

        # Extract the relevant diff hunk for this file
        diff_hunk = self._extract_diff_hunk(diff, file_path)

        # Get full file content at the base ref for context
        file_content = self.github.get_file_content_at_ref(
            owner,
            repo,
            file_path,
            pr_info.get("base_branch", ""),
            github_token,
        )
        if file_content is None:
            file_content = "# (file not accessible)"

        # Detect language from extension
        ext = file_path.rsplit(".", 1)[-1] if "." in file_path else ""
        language = {
            "py": "python",
            "js": "javascript",
            "ts": "typescript",
            "java": "java",
            "go": "go",
            "rs": "rust",
            "rb": "ruby",
            "sh": "bash",
            "yaml": "yaml",
            "yml": "yaml",
            "json": "json",
            "tf": "hcl",
            "md": "markdown",
            "html": "html",
            "css": "css",
        }.get(ext, "")

        # Get other comments on this PR for context
        all_comments = self.github.get_pr_review_comments(
            owner, repo, pr_number, github_token
        )
        other_comment_lines = "\n".join(
            f"- @{c['user']} on {c['path']}:{c.get('line', '?')}: "
            f'"{c["body"][:120]}..."'
            for c in all_comments
            if c["id"] != comment_id
        )
        if not other_comment_lines:
            other_comment_lines = "(no other comments)"

        # Invoke LLM
        system_msg = SystemMessage(content=self._prompts["COMMENT_REVIEW_SYSTEM_PROMPT"])
        human_msg = HumanMessage(
            content=self._prompts["COMMENT_REVIEW_HUMAN_PROMPT"].format(
                repo=f"{owner}/{repo}",
                pr_number=pr_number,
                title=pr_info.get("title", ""),
                base_branch=pr_info.get("base_branch", ""),
                head_branch=pr_info.get("head_branch", ""),
                comment_author=comment_author,
                comment_body=comment_body,
                file_path=file_path,
                line=line,
                diff_hunk=diff_hunk,
                language=language,
                file_content=file_content,
                other_comments=other_comment_lines,
            )
        )

        logger.debug("Invoking Bedrock LLM for comment analysis...")
        llm = self._make_llm(max_tokens=2048, temperature=0.2)
        response = self._invoke_with_budget(llm, [system_msg, human_msg])
        raw_content = str(response.content)
        logger.debug("Raw LLM response: %s", raw_content[:300])

        # Parse structured output
        suggestion = self._parse_comment_response(raw_content)

        # Build reply body
        reply_body = self._build_reply(suggestion)
        includes_suggestion = suggestion.suggested_code is not None

        # Post reply
        self.github.reply_to_review_comment(
            owner, repo, pr_number, comment_id, reply_body, github_token
        )
        logger.info("Replied to comment %d on %s/%s PR #%d", comment_id, owner, repo, pr_number)

        return CommentAnalysisResult(
            comment_id=comment_id,
            pr_owner=owner,
            pr_repo=repo,
            pr_number=pr_number,
            original_comment_body=comment_body,
            reply_body=reply_body,
            includes_suggestion=includes_suggestion,
            raw_response=raw_content,
        )

    def review_and_post(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        github_token: str | None = None,
    ) -> dict[str, Any]:
        """Convenience: run full review, generate comment, post to GitHub."""
        result = self.review(owner, repo, pr_number, github_token)
        comment = self.generate_comment(result, github_token)
        self.github.post_issue_comment(
            owner, repo, pr_number, comment, github_token
        )
        logger.info("Posted review comment to %s/%s PR #%d", owner, repo, pr_number)
        return result.model_dump()

    def review_comment_and_post(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        comment_id: int,
        github_token: str | None = None,
    ) -> dict[str, Any]:
        """Convenience: analyze a comment, reply, return result dict."""
        result = self.review_comment(
            owner, repo, pr_number, comment_id, github_token
        )
        return result.model_dump()

    # ── Helpers ──────────────────────────────────────────────────────

    def _parse_review_response(self, raw: Any) -> dict[str, Any]:
        """Extract structured JSON from the PR review LLM response."""
        content = str(raw).strip()
        if content.startswith("```"):
            lines = content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1:
            logger.error("No JSON found in LLM response: %s", content[:500])
            return {
                "summary": {
                    "total_files": 0,
                    "total_issues": 0,
                    "critical_count": 0,
                    "high_count": 0,
                    "medium_count": 0,
                    "low_count": 0,
                    "score": 0,
                    "strengths": [],
                    "recommendations": ["Failed to parse review response"],
                },
                "issues": [],
            }
        content = content[start : end + 1]
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("JSON parse error: %s", exc)
            return {
                "summary": {
                    "total_files": 0,
                    "total_issues": 0,
                    "critical_count": 0,
                    "high_count": 0,
                    "medium_count": 0,
                    "low_count": 0,
                    "score": 0,
                    "strengths": [],
                    "recommendations": [f"Failed to parse review: {exc}"],
                },
                "issues": [],
            }

    def _parse_comment_response(self, raw: str) -> CommentSuggestion:
        """Extract structured JSON from the comment analysis LLM response."""
        content = raw.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1:
            logger.error("No JSON found in comment LLM response: %s", raw[:300])
            return CommentSuggestion(
                agrees=False,
                explanation="I was unable to analyze this comment. "
                "Please provide more context or clarify the request.",
            )

        content = content[start : end + 1]
        try:
            data = json.loads(content)
            return CommentSuggestion(**data)
        except (json.JSONDecodeError, Exception) as exc:
            logger.error("Comment parse error: %s", exc)
            return CommentSuggestion(
                agrees=False,
                explanation=f"I encountered an error analyzing this comment: {exc}",
            )

    def _build_reply(self, suggestion: CommentSuggestion) -> str:
        """Build a GitHub comment body from a CommentSuggestion."""
        parts = [suggestion.explanation]

        if suggestion.suggested_code:
            # Wrap in a GitHub suggestion block
            parts.append(
                "\n\n```suggestion\n" + suggestion.suggested_code + "\n```"
            )

        return "\n\n".join(parts)

    def _extract_diff_hunk(self, diff: str, file_path: str) -> str:
        """Extract the diff hunk(s) for a specific file from a unified diff."""
        lines = diff.splitlines()
        result = []
        in_target = False

        for line in lines:
            if line.startswith("--- a/") or line.startswith("+++ b/"):
                in_target = file_path in line
                if in_target:
                    result.append(line)
                continue
            if in_target:
                result.append(line)
                # Hunks end at the next file header
                if line.startswith("diff --git"):
                    break

        return "\n".join(result) if result else f"(diff hunk not found for {file_path})"
