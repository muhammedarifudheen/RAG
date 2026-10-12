locals {
  prefix = "atlas-${var.environment}"

  apis = [
    "artifactregistry.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "sqladmin.googleapis.com",
    "sts.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.apis)

  service            = each.value
  disable_on_destroy = false
}

# --- Container images ---------------------------------------------------------

resource "google_artifact_registry_repository" "images" {
  repository_id = local.prefix
  location      = var.region
  format        = "DOCKER"
  description   = "Atlas container images (${var.environment})"

  depends_on = [google_project_service.apis]
}

# --- Postgres 16 with pgvector ------------------------------------------------
#
# pgvector ships with Cloud SQL for PostgreSQL; migration 0001 enables it with
# CREATE EXTENSION, which the user created below is allowed to run.

resource "google_sql_database_instance" "main" {
  name                = "${local.prefix}-pg"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = var.db_deletion_protection

  settings {
    tier              = var.db_tier
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_size         = 10
    disk_autoresize   = true

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }

    # A public address with no authorised networks: nothing can connect to it
    # directly. Cloud Run reaches the database through the Cloud SQL connector,
    # which authenticates with IAM and encrypts the connection.
    ip_configuration {
      ipv4_enabled = true
      ssl_mode     = "ENCRYPTED_ONLY"
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_sql_database" "atlas" {
  name     = "atlas"
  instance = google_sql_database_instance.main.name
}

resource "random_password" "db" {
  length = 32
  # Letters and digits only, so the password needs no escaping inside a URL.
  special = false
}

resource "google_sql_user" "atlas" {
  name     = "atlas"
  instance = google_sql_database_instance.main.name
  password = random_password.db.result
}

# --- Secrets ------------------------------------------------------------------

resource "google_secret_manager_secret" "database_url" {
  secret_id = "${local.prefix}-database-url"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "database_url" {
  secret = google_secret_manager_secret.database_url.id
  # The host is the Unix socket Cloud Run mounts for the Cloud SQL connector.
  secret_data = "postgresql+psycopg://${google_sql_user.atlas.name}:${random_password.db.result}@/${google_sql_database.atlas.name}?host=/cloudsql/${google_sql_database_instance.main.connection_name}"
}

# Created empty on purpose. Add the key yourself so it never enters Terraform
# state or CI:
#   printf '%s' "$KEY" | gcloud secrets versions add <name> --data-file=-
resource "google_secret_manager_secret" "anthropic_api_key" {
  secret_id = "${local.prefix}-anthropic-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

# --- Identity the services and jobs run as ------------------------------------

resource "google_service_account" "runtime" {
  account_id   = "${local.prefix}-runtime"
  display_name = "Atlas ${var.environment} runtime"
}

resource "google_project_iam_member" "runtime_cloudsql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = google_service_account.runtime.member
}

resource "google_secret_manager_secret_iam_member" "runtime_secrets" {
  for_each = {
    database_url      = google_secret_manager_secret.database_url.id
    anthropic_api_key = google_secret_manager_secret.anthropic_api_key.id
  }

  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.runtime.member
}

# The web app needs no Google Cloud access at all. Giving it its own identity
# keeps it off the project's default service account, which is usually over-privileged.
resource "google_service_account" "web" {
  account_id   = "${local.prefix}-web"
  display_name = "Atlas ${var.environment} web (no roles)"
}

# --- Identity GitHub Actions deploys as (no stored key) -----------------------

resource "google_service_account" "deployer" {
  account_id   = "${local.prefix}-deployer"
  display_name = "Atlas ${var.environment} deployer (GitHub Actions)"
}

resource "google_project_iam_member" "deployer_run" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = google_service_account.deployer.member
}

resource "google_artifact_registry_repository_iam_member" "deployer_push" {
  repository = google_artifact_registry_repository.images.name
  location   = google_artifact_registry_repository.images.location
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.deployer.member
}

# Lets the deployer start services and jobs that run as these accounts.
resource "google_service_account_iam_member" "deployer_acts_as" {
  for_each = {
    runtime = google_service_account.runtime.name
    web     = google_service_account.web.name
  }

  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.deployer.member
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "${local.prefix}-github"
  display_name              = "GitHub Actions (${var.environment})"

  depends_on = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Tokens from any other repository or branch are rejected outright.
  attribute_condition = "assertion.repository == \"${var.github_repository}\" && assertion.ref == \"refs/heads/${var.deploy_branch}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_impersonates_deployer" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}
