resource "aws_bedrock_guardrail" "this" {
  name = "${var.cluster_name}-guardrail"

  # Shown when the guardrail blocks content for safety reasons.
  # Note: folio-org scope enforcement happens at the application layer
  # (main.py) before Bedrock is called — these messages cover content-safety
  # blocks only (hate speech, violence, misconduct, prompt injection, etc.).
  blocked_input_messaging   = "This content was blocked by the safety policy and cannot be processed."
  blocked_outputs_messaging = "This response was blocked by the safety policy and cannot be displayed."

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

  # topic_policy_config intentionally removed.
  #
  # The "non-folio-code-review" deny topic was matching on *diff content*
  # (e.g. Dockerfiles referencing external images, MCP configs with third-party
  # URLs) rather than on *user intent*, causing false-positive blocks on
  # legitimate folio-org PRs.  folio-org scope is enforced at the API layer
  # (main.py /review and /review/comment endpoints) before Bedrock is called,
  # so a guardrail topic restriction here is both redundant and harmful.

  tags = var.tags
}

resource "aws_bedrock_guardrail_version" "this" {
  guardrail_arn = aws_bedrock_guardrail.this.guardrail_arn
  description   = "Stable version for ${var.cluster_name}"
}
