from __future__ import annotations

import datetime
import json
import logging
from typing import Any

import boto3

from src.config import get_settings

logger = logging.getLogger(__name__)

# Claude Haiku 4.5 pricing per 1M tokens
PRICING_INPUT_PER_M = 1.00
PRICING_OUTPUT_PER_M = 5.00


class MonthlyUsage:
    """In-memory representation of token usage for the current month."""

    def __init__(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    @property
    def cost(self) -> float:
        return (
            self.input_tokens * PRICING_INPUT_PER_M
            + self.output_tokens * PRICING_OUTPUT_PER_M
        ) / 1_000_000

    def add(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost, 4),
        }


class TokenBudget:
    """Tracks monthly Bedrock token usage via S3 and enforces a hard budget cap.

    Usage data is stored at ``s3://<bucket>/<prefix>/YYYY-MM.json`` so that
    all pods share the same counter (and it survives restarts).
    """

    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self._s3 = boto3.client("s3", region_name=self.settings.aws_region)
        self._budget_dollars = self.settings.monthly_budget_dollars
        self._prefix = self.settings.s3_token_prefix
        self._bucket = self.settings.s3_token_bucket
        self._current: MonthlyUsage | None = None

    # ── Public API ───────────────────────────────────────────────────

    def check(self) -> None:
        """Raise if the monthly budget has been exceeded.

        Called *before* each Bedrock invocation.
        """
        usage = self._get_usage()
        if usage.cost >= self._budget_dollars:
            raise BudgetExceededError(
                f"Monthly Bedrock budget of ${self._budget_dollars:.0f} "
                f"has been reached (${usage.cost:.2f} spent so far). "
                "The token budget will reset at the start of next month."
            )

    def record(self, input_tokens: int, output_tokens: int) -> MonthlyUsage:
        """Record token usage from a completed Bedrock invocation.

        Reads the latest from S3 (another pod may have written since we
        last read), adds the new tokens, and writes back.
        """
        usage = self._load_from_s3()
        usage.add(input_tokens, output_tokens)
        self._save_to_s3(usage)
        self._current = usage
        logger.info(
            "Token usage recorded: +%d in / +%d out = $%.4f (total $%.2f)",
            input_tokens,
            output_tokens,
            (
                input_tokens * PRICING_INPUT_PER_M
                + output_tokens * PRICING_OUTPUT_PER_M
            )
            / 1_000_000,
            usage.cost,
        )
        return usage

    # ── Internals ────────────────────────────────────────────────────

    def _key(self) -> str:
        now = datetime.datetime.now(datetime.timezone.utc)
        return f"{self._prefix}/{now.year}-{now.month:02d}.json"

    def _get_usage(self) -> MonthlyUsage:
        """Return current usage, cached for the duration of the request."""
        if self._current is not None:
            return self._current
        self._current = self._load_from_s3()
        return self._current

    def _load_from_s3(self) -> MonthlyUsage:
        """Read this month's usage from S3, or return an empty counter."""
        try:
            resp = self._s3.get_object(Bucket=self._bucket, Key=self._key())
            data = json.loads(resp["Body"].read().decode("utf-8"))
            return MonthlyUsage(
                input_tokens=data.get("input_tokens", 0),
                output_tokens=data.get("output_tokens", 0),
            )
        except self._s3.exceptions.NoSuchKey:
            return MonthlyUsage()
        except Exception:
            logger.warning("Failed to read token budget from S3", exc_info=True)
            return MonthlyUsage()

    def _save_to_s3(self, usage: MonthlyUsage) -> None:
        """Write this month's usage back to S3."""
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            payload = {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cost_usd": round(usage.cost, 4),
                "last_updated": now.isoformat(),
            }
            self._s3.put_object(
                Bucket=self._bucket,
                Key=self._key(),
                Body=json.dumps(payload, indent=2).encode("utf-8"),
                ContentType="application/json",
            )
        except Exception:
            logger.warning("Failed to write token budget to S3", exc_info=True)


class BudgetExceededError(Exception):
    """Raised when the monthly Bedrock token budget has been exhausted."""
