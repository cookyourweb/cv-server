# --- Cloud SQL: UNUSED --------------------------------------------------------
#
# Applied on 19 Nov 2026 "for the future", but the app uses Neon (shared with
# Render) and nothing connects to this instance. It costs about 9.4 USD/month
# at list price (db-f1-micro 0.0105 USD/h + 10 GiB SSD at 0.17 USD/GiB-month,
# europe-west1, Cloud Billing catalog, 20 Nov 2026) and has backups disabled.
#
# PROPOSED: remove it by setting cloud_sql_enabled = false (RUNBOOK phase 6).
# Not done in this PR: deleting a database is Vero's decision.

resource "google_sql_database_instance" "postgres" {
  count = var.cloud_sql_enabled ? 1 : 0

  name             = "cv-server-db"
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier              = var.db_tier
    availability_type = "ZONAL"
    disk_size         = 10
    disk_autoresize   = true
  }

  deletion_protection = false

  depends_on = [google_project_service.servicios]
}

resource "google_sql_database" "cv_server" {
  count = var.cloud_sql_enabled ? 1 : 0

  name     = "cvserver"
  instance = google_sql_database_instance.postgres[0].name
}

moved {
  from = google_sql_database_instance.postgres
  to   = google_sql_database_instance.postgres[0]
}

moved {
  from = google_sql_database.cv_server
  to   = google_sql_database.cv_server[0]
}
