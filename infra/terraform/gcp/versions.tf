terraform {
  # Same minor as the machine that applied this state (1.9.8) and as CI.
  required_version = ">= 1.9.0, < 2.0.0"

  required_providers {
    google = {
      source = "hashicorp/google"
      # Exact pin: the version that applied the live state (lock file committed).
      # Upgrade on purpose, in its own PR, with a reviewed `terraform plan`.
      version = "5.45.2"
    }
  }

  # Remote state with object versioning: every apply keeps the previous state
  # as a recoverable object version, and the GCS backend locks during apply.
  # The bucket is created once, outside this config (docs/RUNBOOK-gke.md, phase 0),
  # because a config cannot store its state in a bucket it has not created yet.
  backend "gcs" {
    bucket = "cv-server-portfolio-tfstate"
    prefix = "gcp/cv-server"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
