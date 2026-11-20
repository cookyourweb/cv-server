# --- Application config in Secret Manager (ADR-014) ---------------------------
#
# Terraform creates the secret CONTAINER only. Values are added as versions with
# infra/secrets/subir-a-secret-manager.sh, so they never enter the Terraform state.

resource "google_secret_manager_secret" "cv_server_env" {
  secret_id = "cv-server-env"

  # Data stays in the EU region where the cluster runs.
  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  labels = {
    app = "cv-server"
  }

  depends_on = [google_project_service.servicios]
}

# The identity External Secrets uses to read that ONE secret.
resource "google_service_account" "secretos" {
  account_id   = "cv-server-secrets"
  display_name = "Reads the cv-server-env secret (External Secrets)"
}

resource "google_secret_manager_secret_iam_member" "secretos_lector" {
  secret_id = google_secret_manager_secret.cv_server_env.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.secretos.email}"
}

# Workload Identity: only the Kubernetes service account
# default/cv-server-secrets (rendered by the Helm chart) may act as it.
resource "google_service_account_iam_member" "secretos_workload_identity" {
  service_account_id = google_service_account.secretos.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.app_namespace}/cv-server-secrets]"
}
