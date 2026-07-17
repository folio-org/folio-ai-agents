variable "aws_region" {
  description = "The AWS region where resources will be deployed."
  type        = string
  default     = "us-west-2"
}

variable "cluster_name" {
  description = "The name of the EKS cluster."
  type        = string
  default     = "rancher"
}

variable "service_account_namespaces" {
  description = "Kubernetes namespaces whose service accounts are allowed to assume the Bedrock role."
  type        = list(string)
  default     = ["ai-agents"]
}

variable "additional_service_account_subjects" {
  description = "Additional IRSA subjects allowed to assume the Bedrock role (format: system:serviceaccount:namespace:name)."
  type        = list(string)
  default     = ["system:serviceaccount:ai-agents:backend-ai"]
}

variable "service_account_name" {
  description = "Kubernetes service account name that will assume the Bedrock role."
  type        = string
  default     = "backend-ai"
}

variable "bedrock_model_id" {
  description = "Bedrock model ID (or cross-region inference profile) for Anthropic Claude."
  type        = string
  default     = "anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "bedrock_max_tokens" {
  description = "Maximum number of tokens in the model response."
  type        = number
  default     = 2048
}

variable "bedrock_temperature" {
  description = "Sampling temperature for Anthropic Claude Haiku (lower = more deterministic)."
  type        = number
  default     = 0.1
}

variable "bedrock_top_p" {
  description = "Top-p sampling parameter for Anthropic Claude Haiku."
  type        = number
  default     = 0.9
}

variable "data_bucket" {
  description = "S3 bucket for AI agent data: prompt templates (overridable without redeploy) and monthly Bedrock token-usage tracking for budget enforcement."
  type        = string
  default     = "folio-ai-agents-prompts"
}

variable "bedrock_monthly_budget_usd" {
  description = "Monthly budget for Amazon Bedrock usage (USD). Budgets are alert-only — hard enforcement is handled by the app-level S3 token tracker."
  type        = number
  default     = 100
}

variable "budget_alert_email" {
  description = "Email address to receive budget threshold alerts."
  type        = string
  default     = "Eldiiar_Duishenaliev@epam.com"
}

variable "tags" {
  description = "Default tags to apply to resources."
  type        = map(any)
  default = {
    Terraform = "true"
    Project   = "folio"
  }
}
