output "cluster_name" {
  description = "Nombre del cluster GKE"
  value       = google_container_cluster.cv_server.name
}

output "cluster_endpoint" {
  description = "Endpoint del API server (sensible)"
  value       = google_container_cluster.cv_server.endpoint
  sensitive   = true
}

output "get_credentials_command" {
  description = "Comando para apuntar kubectl al cluster"
  value       = "gcloud container clusters get-credentials ${google_container_cluster.cv_server.name} --zone ${var.zone} --project ${var.project_id}"
}

output "artifact_registry_url" {
  description = "Prefijo de las imágenes (docker push aquí)"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.cv_server.repository_id}"
}

output "db_connection_name" {
  description = "Connection name de Cloud SQL (para Cloud SQL Auth Proxy)"
  value       = google_sql_database_instance.postgres.connection_name
}
