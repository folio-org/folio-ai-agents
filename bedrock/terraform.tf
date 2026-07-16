terraform {
  backend "s3" {
    bucket       = "folio-ai-agents-terraform-state"
    key          = "terraform/bedrock.tfstate"
    region       = "us-west-2"
    encrypt      = true
    use_lockfile = true
  }
}
