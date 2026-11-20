# --- Node identity (least privilege) ------------------------------------------
#
# The live nodes run as the Compute Engine default service account, which has
# the project-wide Editor role: any process on a node could change the project.
# The `general` pool uses this account instead.

resource "google_service_account" "nodos" {
  account_id   = "gke-nodes"
  display_name = "GKE nodes of ${var.cluster_name}"
}

# Google's predefined minimum for GKE nodes: write logs and metrics, read
# resource metadata. Nothing else.
resource "google_project_iam_member" "nodos" {
  for_each = toset(["roles/container.defaultNodeServiceAccount"])

  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.nodos.email}"
}

# Pull images from this repository only, not from every registry in the project.
resource "google_artifact_registry_repository_iam_member" "nodos_pull" {
  location   = google_artifact_registry_repository.cv_server.location
  repository = google_artifact_registry_repository.cv_server.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.nodos.email}"
}
