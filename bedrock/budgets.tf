# ── Monthly Budget for Amazon Bedrock ────────────────────────────────
# Alerts are sent at 50%, 80%, 90%, and 100% of the $1,000 limit.
# This does NOT cap spend — AWS Budgets are alert-only.
# A hard application-level cap is enforced via the S3 token tracker.

resource "aws_sns_topic" "budget_alerts" {
  name         = "${var.cluster_name}-bedrock-budget"
  display_name = "Bedrock Budget Alerts"
  tags         = var.tags
}

resource "aws_sns_topic_subscription" "budget_email" {
  topic_arn = aws_sns_topic.budget_alerts.arn
  protocol  = "email"
  endpoint  = var.budget_alert_email
}

resource "aws_budgets_budget" "bedrock" {
  name         = "${var.cluster_name}-bedrock-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.bedrock_monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  time_period_start = "2026-01-01_00:00"

  cost_filter {
    name   = "Service"
    values = ["Amazon Bedrock"]
  }

  # SNS notifications at multiple thresholds
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_sns_topic_arns  = [aws_sns_topic.budget_alerts.arn]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_sns_topic_arns  = [aws_sns_topic.budget_alerts.arn]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 90
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_sns_topic_arns  = [aws_sns_topic.budget_alerts.arn]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_sns_topic_arns  = [aws_sns_topic.budget_alerts.arn]
  }

  tags = var.tags
}
