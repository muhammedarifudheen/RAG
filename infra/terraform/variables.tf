variable "project_id" {
  description = "Google Cloud project to deploy into."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Cloud SQL and Artifact Registry, e.g. asia-south1."
  type        = string
}

variable "github_repository" {
  description = "GitHub repository allowed to deploy, as owner/name."
  type        = string

  validation {
    condition     = can(regex("^[^/]+/[^/]+$", var.github_repository))
    error_message = "github_repository must look like owner/name."
  }
}

variable "environment" {
  description = "Environment name, used in every resource name."
  type        = string
  default     = "staging"
}

variable "deploy_branch" {
  description = "Only workflows running on this branch may deploy."
  type        = string
  default     = "main"
}

variable "db_tier" {
  description = "Cloud SQL machine type. The default is one vCPU and 3.75 GB."
  type        = string
  default     = "db-custom-1-3840"
}

variable "db_deletion_protection" {
  description = "Refuse to destroy the database instance. Set to false before `terraform destroy`."
  type        = bool
  default     = true
}
