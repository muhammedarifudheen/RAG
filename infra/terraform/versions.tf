terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 8.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6"
    }
  }

  # State is local by default and contains the database password. Before more
  # than one person applies this, move it to a bucket:
  #
  # backend "gcs" {
  #   bucket = "<your-state-bucket>"
  #   prefix = "atlas/staging"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
