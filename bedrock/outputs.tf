output "bedrock_role_arn" {
  description = "The ARN of the IAM role for Bedrock access."
  value       = aws_iam_role.bedrock_role.arn
}

output "bedrock_role_name" {
  description = "The name of the IAM role for Bedrock access."
  value       = aws_iam_role.bedrock_role.name
}

output "guardrail_id" {
  description = "The ID of the Bedrock guardrail."
  value       = aws_bedrock_guardrail.this.guardrail_id
}

output "guardrail_arn" {
  description = "The ARN of the Bedrock guardrail."
  value       = aws_bedrock_guardrail.this.guardrail_arn
}

output "guardrail_version" {
  description = "The deployed version of the Bedrock guardrail."
  value       = aws_bedrock_guardrail_version.this.version
}

output "bedrock_env_vars" {
  description = "Env var values to add to the application configuration when BedrockService is implemented."
  value = {
    BEDROCK_MODEL_ID          = var.bedrock_model_id
    BEDROCK_REGION            = var.aws_region
    BEDROCK_MAX_TOKENS        = tostring(var.bedrock_max_tokens)
    BEDROCK_TEMPERATURE       = tostring(var.bedrock_temperature)
    BEDROCK_TOP_P             = tostring(var.bedrock_top_p)
    BEDROCK_GUARDRAIL_ID      = aws_bedrock_guardrail.this.guardrail_id
    BEDROCK_GUARDRAIL_VERSION = aws_bedrock_guardrail_version.this.version
  }
}
