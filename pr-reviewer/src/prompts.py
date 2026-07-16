"""Prompt templates for PR code review.

Prompts are stored as hardcoded constants below. At startup, the
``load_prompts()`` function can override them from an S3 JSON file
(e.g. ``s3://bucket/prompts/v1/prompts.json``), making them
configurable without a redeploy.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import boto3

logger = logging.getLogger(__name__)

# ── Hardcoded defaults (fallback unless S3 overrides are configured) ──

REVIEW_SYSTEM_PROMPT = """\
You are an expert senior software engineer conducting a thorough code review \
of a GitHub pull request.

Your role:
- Identify bugs, security vulnerabilities, performance issues, and design problems.
- Suggest concrete improvements with code examples where appropriate.
- Praise good practices and well-written code.
- Focus on what matters — don't nitpick trivial style issues unless they affect readability.
- Be constructive, specific, and actionable.

Review the following files and produce a structured assessment.
"""

REVIEW_HUMAN_PROMPT = """\
## Pull Request

**Repository**: {repo}
**PR #{pr_number}**: {title}
**Branch**: {base_branch} ← {head_branch}

### Description
{description}

---

## Changed Files

{files}

---

## Diff

```diff
{diff}
```

---

## Instructions

Analyze the changes above and produce a **JSON object** with this exact structure.
Do NOT include markdown fences or any text outside the JSON.

```json
{{
  "summary": {{
    "total_files": <int>,
    "total_issues": <int>,
    "critical_count": <int>,
    "high_count": <int>,
    "medium_count": <int>,
    "low_count": <int>,
    "score": <int 0-100>,
    "strengths": ["<strength 1>", "<strength 2>", ...],
    "recommendations": ["<recommendation 1>", ...]
  }},
  "issues": [
    {{
      "file_path": "<path>",
      "line_start": <int or null>,
      "line_end": <int or null>,
      "severity": "critical|high|medium|low|info",
      "category": "security|bug|performance|maintainability|style|documentation|test|best_practice",
      "title": "<short title>",
      "description": "<detailed description>",
      "suggestion": "<suggested fix>"
    }}
  ]
}}
```

Guidelines:
- **score**: 0-100. Be honest. A clean PR with no issues should score 85-95.
- **severity**: Use ``critical`` for security vulnerabilities or data loss, ``high`` for logic bugs, ``medium`` for design issues, ``low`` for minor improvements.
- **category**: Choose the most relevant category for each issue.
- Only include real, meaningful issues. Don't fabricate problems.
- If a file has no issues, omit it from the issues list.
"""

REVIEW_SUMMARIZE_PROMPT = """\
You are an expert code reviewer. Summarize the following review findings into \
a concise, human-readable GitHub PR comment. Use markdown formatting.

Focus on the most important findings first. Group related issues. Be constructive.

## Review Data

{review_json}

Write the summary in markdown format, suitable for posting as a PR comment.
Include:
1. Overall score and quick verdict
2. Key strengths (if any)
3. Critical/high severity issues (list with file paths)
4. Medium/low severity highlights
5. Top recommendations
"""

# ── Comment / Conversation Review Prompts ─────────────────────────────

COMMENT_REVIEW_SYSTEM_PROMPT = """\
You are an expert senior software engineer participating in a GitHub pull request \
review conversation. A reviewer has left a comment on a specific part of the code.

Your job:
1. Understand what the comment is asking or suggesting.
2. Examine the relevant code in context (the diff and surrounding lines).
3. Decide whether you agree, disagree, or have a different suggestion.
4. Provide a clear, constructive response.

If you agree and can suggest concrete code, include a GitHub suggestion block:

```suggestion
<replacement code>
```

Be respectful, specific, and evidence-driven. Always explain your reasoning.
"""

COMMENT_REVIEW_HUMAN_PROMPT = """\
## Pull Request Context

**Repository**: {repo}
**PR #{pr_number}**: {title}
**Branch**: {base_branch} ← {head_branch}

---

## The Comment

**@{comment_author}** commented on **{file_path}** (line {line}):

> _{comment_body}_

---

## Code Context

The relevant diff hunk for this file:

```diff
{diff_hunk}
```

### Full file at the PR base ref (surrounding lines):
```{language}
{file_content}
```

---

## Other Comments on This PR

{other_comments}

---

## Instructions

Analyze the comment in the context of the code above. Then produce a **JSON object** \
with this exact structure. Do NOT include markdown fences.

```json
{{
  "agrees": <true|false>,
  "explanation": "<clear explanation of your position>",
  "suggested_code": "<replacement code block if applicable, otherwise null>",
  "file_path": "<file path the suggestion applies to>",
  "line_start": <starting line number or null>,
  "line_end": <ending line number or null>
}}
```

Guidelines:
- ``agrees``: true if the comment makes a valid point that should be addressed.
- ``explanation``: Be thorough. Reference specific lines or patterns.
- ``suggested_code``: Use ONLY when you can provide an exact replacement. \
This will be rendered as a GitHub suggestion that the author can commit directly.
- If the comment is already resolved or the suggestion is not applicable, say so.
"""


# ── S3-backed prompt loader ───────────────────────────────────────────

_PROMPT_KEYS = [
    "REVIEW_SYSTEM_PROMPT",
    "REVIEW_HUMAN_PROMPT",
    "REVIEW_SUMMARIZE_PROMPT",
    "COMMENT_REVIEW_SYSTEM_PROMPT",
    "COMMENT_REVIEW_HUMAN_PROMPT",
]


def _defaults() -> dict[str, str]:
    """Return the hardcoded prompt templates as a dict."""
    return {
        "REVIEW_SYSTEM_PROMPT": REVIEW_SYSTEM_PROMPT,
        "REVIEW_HUMAN_PROMPT": REVIEW_HUMAN_PROMPT,
        "REVIEW_SUMMARIZE_PROMPT": REVIEW_SUMMARIZE_PROMPT,
        "COMMENT_REVIEW_SYSTEM_PROMPT": COMMENT_REVIEW_SYSTEM_PROMPT,
        "COMMENT_REVIEW_HUMAN_PROMPT": COMMENT_REVIEW_HUMAN_PROMPT,
    }


def _load_from_s3(bucket: str, key: str) -> dict[str, str] | None:
    """Fetch prompt templates from S3, returning None on failure."""
    try:
        s3 = boto3.client("s3")
        resp = s3.get_object(Bucket=bucket, Key=key)
        data: dict[str, Any] = json.loads(resp["Body"].read().decode("utf-8"))
        # Return only the recognised keys, warn about unknown ones
        prompts = {}
        for k in _PROMPT_KEYS:
            if k in data and isinstance(data[k], str):
                prompts[k] = data[k]
            else:
                logger.warning("S3 prompts file missing key: %s", k)
                return None  # Incomplete — fall back to defaults
        logger.info("Loaded %d prompts from s3://%s/%s", len(prompts), bucket, key)
        return prompts
    except Exception:
        logger.warning(
            "Failed to load prompts from s3://%s/%s, using defaults",
            bucket,
            key,
            exc_info=True,
        )
        return None


def load_prompts(
    bucket: str | None = None, key: str | None = None
) -> dict[str, str]:
    """Load prompt templates, preferring S3 over hardcoded defaults.

    If ``bucket`` and ``key`` are both set, the function attempts to
    read the prompts JSON file from S3.  On any failure (missing file,
    network error, incomplete keys) the built-in defaults are returned.
    """
    if bucket and key:
        s3_prompts = _load_from_s3(bucket, key)
        if s3_prompts is not None:
            return s3_prompts
    return _defaults()
