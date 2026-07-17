# AI Code Review for folio-org Repositories

Automated AI-powered pull request reviews using AWS Bedrock Claude Haiku 4.5.

## Architecture

The system consists of three components:

1. **Reusable GitHub Actions Workflow** (`.github/workflows/ai-code-review.yml`)
   - Triggered on PR events from consuming repositories
   - Extracts PR metadata (number, owner, repo) and passes to the review service
   - Posts review comments back to GitHub via GitHub App authentication

2. **Review Service** (FastAPI backend)
   - Deployed on the rancher Kubernetes cluster (`ai-agents` namespace)
   - Receives review requests via webhook
   - Calls AWS Bedrock Claude Haiku 4.5 for code analysis
   - Tracks token usage and enforces budget limits via S3
   - Posts review comments to GitHub using GitHub App credentials

3. **GitHub App** (folio-org)
   - App ID: `4315710`
   - Installation ID: `147000691`
   - Handles authentication for posting reviews without a shared bot token
   - Private key stored in Kubernetes secret

## How it works

1. A PR is opened or updated in a folio-org repository
2. GitHub Actions workflow extracts PR metadata and calls the review service endpoint
3. Review service fetches the PR diff via GitHub API
4. Service calls AWS Bedrock Claude Haiku 4.5 for analysis
5. Token usage is recorded to S3 for budget tracking
6. Review comment is posted back to the PR via GitHub App

## How to enable

Copy [`.github/workflows/samples/ai-code-review-repo.yml`](.github/workflows/samples/ai-code-review-repo.yml) into your repository at `.github/workflows/ai-code-review-repo.yml`:

```yaml
name: AI Code Review

on:
  pull_request:
    types: [opened, synchronize]
  pull_request_review_comment:
    types: [created]
  workflow_dispatch:
    inputs:
      pr_number:
        description: "PR number to review"
        required: true
        type: number
      review_type:
        description: "Review type"
        required: true
        default: "full"
        type: choice
        options:
          - full
          - comment

jobs:
  review:
    uses: folio-org/folio-ai-agents/.github/workflows/ai-code-review.yml@main
    with:
      pr_number: ${{ github.event.inputs.pr_number || github.event.issue.number || github.event.pull_request.number }}
      owner: ${{ github.event.repository.owner.login }}
      repo: ${{ github.event.repository.name }}
    secrets:
      ai_pr_reviewer: ${{ secrets.AI_PR_REVIEWER }}
      gh_token: ${{ github.token }}
```

**Important**: PR metadata is passed explicitly via `with:` — GitHub Actions does not provide event context to reusable workflows. The sample above is ready to use as-is.

## What it does

| Trigger | Action |
|---|---|
| PR opened or new commits pushed | Full code review — analyzes diff and posts a summary comment with issues found and a quality score |
| Manual (`workflow_dispatch`) | Re-review on demand |

## Required secrets

| Secret | Source | Used by |
|---|---|---|
| `AI_PR_REVIEWER` | Organization secret (folio-org) | GitHub Actions workflow; passed to review service |
| `GITHUB_APP_PRIVATE_KEY` | Kubernetes secret (`pr-reviewer-secret`) | Review service; authenticates with GitHub App |
| `GITHUB_WEBHOOK_SECRET` | Kubernetes secret (`pr-reviewer-secret`) | Review service; validates incoming webhooks |

## Cost control

- **AWS Budget**: $1,000/month limit with SNS alerts
- **S3 Token Tracker**: Cumulative token usage recorded in `folio-ai-agents-prompts` S3 bucket
- **Hard stop**: Service rejects requests if monthly budget is exceeded

Current usage: ~$0.07/month (as of 2026-07-16)

## Deployment

The review service is deployed via Helm chart:

```bash
helm upgrade --install pr-reviewer ./charts/pr-reviewer \
  --namespace ai-agents \
  --values values.yaml
```

**Ingress**: `pr-reviewer.ci.folio.org` (part of rancher ALB group)

**Health check**: `GET /health` returns 200 when service and Bedrock are available

## Manual re-review

Go to your repository's **Actions** tab, select the **AI Code Review** workflow, and click **Run workflow**. Specify the PR number to re-review.

## Troubleshooting

| Issue | Solution |
|---|---|
| Workflow does not appear in Actions tab | Ensure `.github/workflows/ai-code-review-repo.yml` is committed to the repo |
| Authentication errors | Check that `AI_PR_REVIEWER` secret is set in the organization |
| Review not posted | Check pod logs: `kubectl logs -n ai-agents -l app=pr-reviewer` |
| Budget exceeded | Contact platform team; AWS Budget alert will be sent to SNS topic |

## Questions?

Contact the platform team if you encounter issues or need to opt out of automatic reviews.
