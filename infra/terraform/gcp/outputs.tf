output "cluster_name" {
  description = "GKE cluster name"
  value       = google_container_cluster.cv_server.name
}

output "cluster_endpoint" {
  description = "API server endpoint (sensitive)"
  value       = google_container_cluster.cv_server.endpoint
  sensitive   = true
}

output "get_credentials_command" {
  description = "Point kubectl at the cluster"
  value       = "gcloud container clusters get-credentials ${google_container_cluster.cv_server.name} --zone ${var.zone} --project ${var.project_id}"
}

output "artifact_registry_url" {
  description = "Image prefix (docker push here)"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.cv_server.repository_id}"
}

output "node_service_account" {
  description = "Least-privilege identity of the general pool nodes"
  value       = google_service_account.nodos.email
}

output "secrets_reader_service_account" {
  description = "GSA that External Secrets impersonates (values.gke.yaml must match)"
  value       = google_service_account.secretos.email
}

output "env_secret_id" {
  description = "Secret Manager secret holding the app env as JSON"
  value       = google_secret_manager_secret.cv_server_env.secret_id
}

output "db_connection_name" {
  description = "Cloud SQL connection name (UNUSED instance, see cloudsql.tf); null once removed"
  value       = one(google_sql_database_instance.postgres[*].connection_name)
}
