# tflint for infra/terraform/gcp and infra/terraform/aws (CI: .github/workflows/infra.yml).
# Plugin versions are pinned, like everything else that runs in CI.

plugin "terraform" {
  enabled = true
  # Unused declarations, missing version pins, deprecated syntax, naming...
  preset = "recommended"
}

plugin "google" {
  enabled = true
  version = "0.41.0"
  source  = "github.com/terraform-linters/tflint-ruleset-google"
}

plugin "aws" {
  enabled = true
  version = "0.50.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}
