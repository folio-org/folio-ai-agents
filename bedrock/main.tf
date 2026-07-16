locals {
  oidc_provider_url = element(split(":oidc-provider/", data.aws_iam_openid_connect_provider.this.arn), 1)
}

resource "aws_iam_role" "bedrock_role" {
  name = "${var.cluster_name}-bedrock-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Principal = {
          Federated = data.aws_iam_openid_connect_provider.this.arn
        },
        Action = "sts:AssumeRoleWithWebIdentity",
        Condition = {
          StringEquals = {
            "${local.oidc_provider_url}:sub" = concat(
              [for ns in var.service_account_namespaces : "system:serviceaccount:${ns}:${var.service_account_name}"],
              var.additional_service_account_subjects
            ),
            "${local.oidc_provider_url}:aud" = "sts.amazonaws.com"
          }
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_policy" "bedrock_policy" {
  name        = "${var.cluster_name}-bedrock-policy"
  description = "Policy granting necessary permissions for AWS Bedrock access."

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:Converse",
          "bedrock:ConverseStream",
          "bedrock:ListFoundationModels",
          "bedrock:GetFoundationModel",
          "bedrock:GetInferenceProfile",
          "bedrock:ListInferenceProfiles",
          "bedrock:ApplyGuardrail"
        ],
        Resource = "*"
      },
      {
        Effect = "Allow",
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ],
        Resource = [
          "arn:aws:s3:::${var.data_bucket}",
          "arn:aws:s3:::${var.data_bucket}/*"
        ]
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "bedrock_attach" {
  role       = aws_iam_role.bedrock_role.name
  policy_arn = aws_iam_policy.bedrock_policy.arn
}

resource "aws_s3_bucket" "prompts" {
  bucket = var.data_bucket

  tags = var.tags
}

resource "aws_s3_bucket_versioning" "prompts" {
  bucket = aws_s3_bucket.prompts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "prompts" {
  bucket = aws_s3_bucket.prompts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "prompts" {
  bucket = aws_s3_bucket.prompts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
