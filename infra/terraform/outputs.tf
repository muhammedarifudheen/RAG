# Each output is the value of the GitHub Actions variable of the same name, to be
# set on the repository's "staging" environment. None of them is secret.

output "GCP_PROJECT_ID" {
  value = var.project_id
}

output "GCP_REGION" {
  value = var.region
}

output "GCP_WORKLOAD_IDENTITY_PROVIDER" {
  value = google_iam_workload_identity_pool_provider.github.name
}

output "GCP_DEPLOYER_SERVICE_ACCOUNT" {
  value = google_service_account.deployer.email
}

output "GCP_RUNTIME_SERVICE_ACCOUNT" {
  value = google_service_account.runtime.email
}

output "GCP_WEB_SERVICE_ACCOUNT" {
  value = google_service_account.web.email
}

output "GCP_ARTIFACT_REPOSITORY" {
  description = "Image path prefix; images are pushed as <this>/<name>:<tag>."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "CLOUD_SQL_CONNECTION_NAME" {
  value = google_sql_database_instance.main.connection_name
}

output "anthropic_api_key_secret" {
  description = "Add a version to this secret before the first deploy."
  value       = google_secret_manager_secret.anthropic_api_key.secret_id
}
