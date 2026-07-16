# AI Code Review for folio-org Repositories

Automated AI-powered pull request reviews using AWS Bedrock Claude Haiku.

## How it works

The review logic lives in a single **reusable workflow** at:

```
folio-org/folio-ai-agents/.github/workflows/ai-code-review.yml
```

Each repo just needs a thin wrapper that references it with `uses:`. When the reusable workflow is updated, all consuming repos automatically get the changes.

## How to enable

Copy [`.github/workflows/samples/ai-code-review-repo.yml`](.github/workflows/samples/ai-code-review-repo.yml) into your repository at:

```
.github/workflows/ai-code-review-repo.yml
```

That's it. The wrapper delegates to the reusable workflow and inherits all necessary secrets.

## What it does

| Trigger | Action |
|---|---|
| PR opened or new commits pushed | Full code review — analyzes diff, files, and posts a summary comment with issues found and a quality score |
| A review comment is created | Analyzes the comment and replies with a code suggestion (if applicable) |
| Manual (`workflow_dispatch`) | Re-review on demand — supports both full and comment review types |

## Required secrets

None in your repo. The workflow inherits:

| Secret | Source |
|---|---|
| `AI_PR_REVIEWER` | Inherited from the `folio-org` organization (set by the platform team) |
| `GITHUB_TOKEN` | Automatically provided by GitHub Actions |

## Version pinning

The sample pins to `@main` — you always get the latest version.

If you prefer stable releases, watch for tags in `folio-ai-agents` and pin to a specific version:

```yaml
uses: folio-org/folio-ai-agents/.github/workflows/ai-code-review.yml@v1
```

## Manual re-review

Go to your repository's **Actions** tab, select the **AI Code Review** workflow, and click **Run workflow**. You can specify a PR number and choose between a full review or comment analysis.

## Questions?

Contact the platform team if:

- The workflow does not appear in your Actions tab
- You see authentication errors (the `AI_PR_REVIEWER` secret might need updating)
- You'd like to opt out of automatic reviews
