from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class IssueCategory(str, Enum):
    security = "security"
    bug = "bug"
    performance = "performance"
    maintainability = "maintainability"
    style = "style"
    documentation = "documentation"
    test = "test"
    best_practice = "best_practice"


class CodeIssue(BaseModel):
    """A single issue found during review."""

    file_path: str = Field(description="Path to the file with the issue")
    line_start: int | None = Field(None, description="Starting line number")
    line_end: int | None = Field(None, description="Ending line number")
    severity: Severity = Field(description="Severity of the issue")
    category: IssueCategory = Field(description="Category of the issue")
    title: str = Field(description="Short title of the issue")
    description: str = Field(description="Detailed description of the issue")
    suggestion: str | None = Field(
        None, description="Suggested fix or improvement"
    )


class ReviewSummary(BaseModel):
    """Overall review summary."""

    total_files: int = Field(description="Total number of files reviewed")
    total_issues: int = Field(description="Total issues found")
    critical_count: int = Field(description="Number of critical issues")
    high_count: int = Field(description="Number of high severity issues")
    medium_count: int = Field(description="Number of medium severity issues")
    low_count: int = Field(description="Number of low severity issues")
    score: int = Field(
        description="Overall code quality score (0-100)",
        ge=0,
        le=100,
    )
    strengths: list[str] = Field(
        default_factory=list, description="Positive aspects of the PR"
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Top recommendations for improvement",
    )


class ReviewResult(BaseModel):
    """Complete result of a PR review."""

    pr_owner: str = Field(description="GitHub repository owner")
    pr_repo: str = Field(description="GitHub repository name")
    pr_number: int = Field(description="Pull request number")
    pr_title: str | None = Field(None, description="PR title")
    pr_description: str | None = Field(None, description="PR description")
    summary: ReviewSummary = Field(description="Overall review summary")
    issues: list[CodeIssue] = Field(
        default_factory=list, description="All issues found"
    )
    raw_response: str | None = Field(
        None,
        description="Raw LLM response text (for debugging)",
    )


class ReviewRequest(BaseModel):
    """Incoming request to review a PR."""

    owner: str = Field(description="GitHub repository owner")
    repo: str = Field(description="GitHub repository name")
    pr_number: int = Field(description="Pull request number")
    github_token: str | None = Field(
        None, description="GitHub personal access token"
    )


# ── Comment Review Models ────────────────────────────────────────────


class CommentReviewRequest(BaseModel):
    """Request to analyze and reply to a PR review comment."""

    owner: str = Field(description="GitHub repository owner")
    repo: str = Field(description="GitHub repository name")
    pr_number: int = Field(description="Pull request number")
    comment_id: int = Field(description="ID of the review comment to analyze")
    github_token: str | None = Field(
        None, description="GitHub personal access token"
    )


class CommentSuggestion(BaseModel):
    """Output from the LLM when analyzing a PR comment."""

    agrees: bool = Field(
        description="Whether the agent agrees with the comment's suggestion"
    )
    explanation: str = Field(
        description="Clear explanation of the position taken"
    )
    suggested_code: str | None = Field(
        None,
        description="Suggested replacement code block (if applicable). "
        "This will be rendered as a GitHub suggestion block.",
    )
    file_path: str | None = Field(
        None,
        description="File path the suggestion applies to",
    )
    line_start: int | None = Field(
        None,
        description="Starting line for the suggestion",
    )
    line_end: int | None = Field(
        None,
        description="Ending line for the suggestion",
    )


class CommentAnalysisResult(BaseModel):
    """Result of analyzing and replying to a PR comment."""

    comment_id: int = Field(description="ID of the original comment")
    pr_owner: str = Field(description="GitHub repository owner")
    pr_repo: str = Field(description="GitHub repository name")
    pr_number: int = Field(description="Pull request number")
    original_comment_body: str = Field(
        description="The original comment that was analyzed"
    )
    reply_body: str = Field(
        description="The reply posted to the comment thread"
    )
    includes_suggestion: bool = Field(
        description="Whether the reply includes a code suggestion"
    )
    raw_response: str | None = Field(
        None,
        description="Raw LLM response text (for debugging)",
    )


class WebhookPayload(BaseModel):
    """GitHub webhook payload (subset of relevant fields)."""

    action: str | None = None
    pull_request: dict[str, Any] | None = None
    repository: dict[str, Any] | None = None
    comment: dict[str, Any] | None = None
    changes: dict[str, Any] | None = None
