resource "aws_bedrock_guardrail" "this" {
  name                      = "${var.cluster_name}-guardrail"
  blocked_input_messaging   = "I can only review code in GitHub repositories under https://github.com/folio-org. Please supply a valid pull request from a folio-org repository."
  blocked_outputs_messaging = "I cannot answer that request. Please ask for a code review on a pull request from a github.com/folio-org repository."

  content_policy_config {
    filters_config {
      type            = "HATE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "INSULTS"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
    filters_config {
      type            = "SEXUAL"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "VIOLENCE"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
    filters_config {
      type            = "MISCONDUCT"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
  }

  topic_policy_config {
    topics_config {
      name       = "non-folio-code-review"
      definition = "Pull requests outside github.com/folio-org, personal repos, or unrelated topics like weather, jokes, or feature generation."
      examples = [
        "Review this PR from a non-folio-org repo",
        "Review code from github.com/example/other",
        "Write a new feature for me",
        "What is the weather today",
        "Tell me a joke"
      ]
      type = "DENY"
    }
  }

  tags = var.tags
}

resource "aws_bedrock_guardrail_version" "this" {
  guardrail_arn = aws_bedrock_guardrail.this.guardrail_arn
  description   = "Stable version for ${var.cluster_name}"
}
