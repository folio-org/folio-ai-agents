from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from src.config import get_settings
from src.models import CommentReviewRequest, ReviewRequest
from src.reviewer import PRReviewer
from src.token_budget import BudgetExceededError

logger = logging.getLogger(__name__)
settings = get_settings()
reviewer = PRReviewer(settings)


def verify_webhook_signature(payload_body: bytes, signature_header: str) -> bool:
    """Verify the X-Hub-Signature-256 header against the webhook secret."""
    secret = settings.github_webhook_secret
    if not secret:
        # If no secret is configured, skip verification (dev mode)
        return True
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), payload_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature_header, expected)


def verify_api_key(request: Request) -> bool:
    """Verify the X-API-Key header against the configured webhook secret.

    This allows GitHub Actions workflows (using the org-level AI_PR_REVIEWER
    secret) to authenticate API calls from individual repos.
    """
    secret = settings.github_webhook_secret
    if not secret:
        return True  # dev mode
    return hmac.compare_digest(
        request.headers.get("X-API-Key", ""), secret
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info(
        "Starting PR Reviewer service, model=%s", settings.bedrock_model_id
    )
    yield
    logger.info("Shutting down PR Reviewer service")


app = FastAPI(
    title="folio-org PR Reviewer",
    description="AI code review agent for folio-org pull requests using AWS Bedrock Claude Haiku",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ──────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "model": settings.bedrock_model_id,
        "region": settings.aws_region,
        "guardrail_configured": bool(settings.bedrock_guardrail_id),
    }


# ── PR Review API ───────────────────────────────────────────────────


@app.post("/review")
async def review_pr(req: ReviewRequest, request: Request):
    """Review an entire GitHub pull request and post a summary comment."""
    if not verify_api_key(request):
        raise HTTPException(status_code=401, detail="Invalid API key")
    if req.owner.lower() != "folio-org":
        raise HTTPException(
            status_code=403,
            detail="Only repositories under github.com/folio-org are supported.",
        )
    try:
        logger.info(
            "Review request: %s/%s PR #%d",
            req.owner,
            req.repo,
            req.pr_number,
        )
        result = reviewer.review_and_post(
            owner=req.owner,
            repo=req.repo,
            pr_number=req.pr_number,
            github_token=req.github_token,
        )
        return {
            "status": "success",
            "type": "pr_review",
            "pr": f"{req.owner}/{req.repo}#{req.pr_number}",
            "score": result.get("summary", {}).get("score"),
            "total_issues": result.get("summary", {}).get("total_issues"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Review failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Comment Review API ──────────────────────────────────────────────


@app.post("/review/comment")
async def review_comment(req: CommentReviewRequest, request: Request):
    """Analyze a specific PR review comment and reply with a suggestion.

    The agent fetches the comment, examines the surrounding code context,
    and posts a reply — optionally including a GitHub suggestion block
    that the PR author can commit directly.
    """
    if not verify_api_key(request):
        raise HTTPException(status_code=401, detail="Invalid API key")
    if req.owner.lower() != "folio-org":
        raise HTTPException(
            status_code=403,
            detail="Only repositories under github.com/folio-org are supported.",
        )
    try:
        logger.info(
            "Comment review request: %s/%s PR #%d comment #%d",
            req.owner,
            req.repo,
            req.pr_number,
            req.comment_id,
        )
        result = reviewer.review_comment_and_post(
            owner=req.owner,
            repo=req.repo,
            pr_number=req.pr_number,
            comment_id=req.comment_id,
            github_token=req.github_token,
        )
        return {
            "status": "success",
            "type": "comment_reply",
            "pr": f"{req.owner}/{req.repo}#{req.pr_number}",
            "comment_id": req.comment_id,
            "includes_suggestion": result.get("includes_suggestion", False),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Comment review failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ── GitHub Webhook ──────────────────────────────────────────────────


@app.post("/webhook")
async def webhook(request: Request):
    """GitHub webhook receiver for automatic reviews on PR events.

    Handles:
    - ``pull_request`` (opened/synchronize) → full PR review
    - ``pull_request_review_comment`` (created) → comment analysis + reply

    Uses the GitHub App installation token for all GitHub API calls
    (the app must be installed on the folio-org organization).
    """
    event = request.headers.get("X-GitHub-Event", "")
    delivery = request.headers.get("X-GitHub-Delivery", "")
    signature = request.headers.get("X-Hub-Signature-256", "")

    # Read raw body for signature verification before JSON parsing
    body_bytes = await request.body()

    if not verify_webhook_signature(body_bytes, signature):
        logger.warning("Webhook signature verification failed [%s]", delivery)
        raise HTTPException(status_code=403, detail="Invalid webhook signature")

    if event not in ("pull_request", "pull_request_review_comment"):
        return {
            "status": "ignored",
            "reason": f"event={event} not handled",
        }

    payload = await request.json()
    action = payload.get("action", "")
    repo_data = payload.get("repository", {})

    owner = repo_data.get("owner", {}).get("login", "")
    repo_name = repo_data.get("name", "")

    if not owner or not repo_name:
        return {"status": "ignored", "reason": "incomplete payload"}

    # Enforce folio-org scope
    if owner.lower() != "folio-org":
        logger.info("Skipping non-folio-org repo: %s/%s", owner, repo_name)
        return {"status": "skipped", "reason": "not folio-org repository"}

    bot_username = settings.github_app_bot_username or "folio-pr-reviewer[bot]"

    # ── PR opened / synchronized → full review ──────────────────────
    if event == "pull_request" and action in ("opened", "synchronize"):
        pr = payload.get("pull_request")
        pr_number = pr.get("number") if pr else None
        if not pr_number:
            return {"status": "ignored", "reason": "missing PR number"}

        logger.info(
            "Webhook PR review: %s/%s PR #%d (%s) [%s]",
            owner,
            repo_name,
            pr_number,
            action,
            delivery,
        )

        asyncio.create_task(_run_review_async(owner, repo_name, pr_number))

        return {
            "status": "accepted",
            "type": "pr_review",
            "pr": f"{owner}/{repo_name}#{pr_number}",
            "action": action,
        }

    # ── PR review comment created → analyze + reply ────────────────
    if event == "pull_request_review_comment" and action == "created":
        comment = payload.get("comment", {})
        pr = payload.get("pull_request", {})
        comment_id = comment.get("id")
        pr_number = pr.get("number")

        if not comment_id or not pr_number:
            return {"status": "ignored", "reason": "missing comment or PR ID"}

        # Avoid replying to our own comments (infinite loop)
        comment_user = (comment.get("user") or {}).get("login", "")
        if comment_user == bot_username:
            return {"status": "skipped", "reason": "own comment"}

        logger.info(
            "Webhook comment review: %s/%s PR #%d comment #%d by @%s [%s]",
            owner,
            repo_name,
            pr_number,
            comment_id,
            comment_user,
            delivery,
        )

        asyncio.create_task(
            _run_comment_review_async(owner, repo_name, pr_number, comment_id)
        )

        return {
            "status": "accepted",
            "type": "comment_reply",
            "pr": f"{owner}/{repo_name}#{pr_number}",
            "comment_id": comment_id,
        }

    return {
        "status": "skipped",
        "reason": f"event={event} action={action} not reviewed",
    }


# ── Background tasks ────────────────────────────────────────────────


async def _run_review_async(owner: str, repo: str, pr_number: int):
    """Run full PR review in background (non-blocking)."""
    try:
        reviewer.review_and_post(owner=owner, repo=repo, pr_number=pr_number)
    except BudgetExceededError:
        logger.warning(
            "Skipping review for %s/%s PR #%d — budget exceeded",
            owner,
            repo,
            pr_number,
        )
    except Exception:
        logger.exception(
            "Background review failed for %s/%s PR #%d",
            owner,
            repo,
            pr_number,
        )


async def _run_comment_review_async(
    owner: str, repo: str, pr_number: int, comment_id: int
):
    """Run comment analysis + reply in background (non-blocking)."""
    try:
        reviewer.review_comment_and_post(
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            comment_id=comment_id,
        )
    except BudgetExceededError:
        logger.warning(
            "Skipping comment review for %s/%s PR #%d — budget exceeded",
            owner,
            repo,
            pr_number,
        )
    except Exception:
        logger.exception(
            "Background comment review failed for %s/%s PR #%d comment #%d",
            owner,
            repo,
            pr_number,
            comment_id,
        )


# ── Entry point ────────────────────────────────────────────────────


def main():
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
