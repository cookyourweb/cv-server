terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # Estado remoto: imprescindible si hay más de una persona o CI.
  # Crear el bucket antes (una sola vez) y descomentar.
  # backend "gcs" {
  #   bucket = "tu-proyecto-tfstate"
  #   prefix = "cv-server"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# --- APIs necesarias -------------------------------------------------------

resource "google_project_service" "servicios" {
  for_each = toset([
    "container.googleapis.com",
    "artifactregistry.googleapis.com",
    "sqladmin.googleapis.com",
  ])
  service            = each.key
  disable_on_destroy = false
}

# --- Registro de imágenes --------------------------------------------------

resource "google_artifact_registry_repository" "cv_server" {
  location      = var.region
  repository_id = "cv-server"
  format        = "DOCKER"
  description   = "Imágenes de cv-server"

  depends_on = [google_project_service.servicios]
}

# --- Base de datos (futuro PostgresSaver / persistencia) --------------------

resource "google_sql_database_instance" "postgres" {
  name             = "cv-server-db"
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier              = var.db_tier
    availability_type = "ZONAL" # REGIONAL (HA) cuesta el doble
    disk_size         = 10
    disk_autoresize   = true
  }

  deletion_protection = false # false para poder hacer terraform destroy sin fricción (demo/portfolio)

  depends_on = [google_project_service.servicios]
}

resource "google_sql_database" "cv_server" {
  name     = "cvserver"
  instance = google_sql_database_instance.postgres.name
}

# --- Cluster de Kubernetes -------------------------------------------------

resource "google_container_cluster" "cv_server" {
  name     = var.cluster_name
  location = var.zone # zonal: 1 nodo de control gratis-ish

  # Buenas prácticas: no usar el nodo por defecto, gestionar node pools aparte.
  remove_default_node_pool = true
  initial_node_count       = 1

  networking_mode = "VPC_NATIVE"
  ip_allocation_policy {}

  release_channel {
    channel = "REGULAR"
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  deletion_protection = false # false para poder hacer terraform destroy sin fricción (demo/portfolio)

  depends_on = [google_project_service.servicios]
}

resource "google_container_node_pool" "principal" {
  name       = "principal"
  location   = var.zone
  cluster    = google_container_cluster.cv_server.name
  node_count = var.node_count

  autoscaling {
    min_node_count = 1
    max_node_count = var.max_node_count
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  node_config {
    machine_type = var.machine_type
    spot         = true # abarata mucho; aceptable para un portfolio
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]

    labels = {
      env = var.env
    }

    # Workload Identity: los pods asumen una service account de GCP sin claves.
    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }
}
