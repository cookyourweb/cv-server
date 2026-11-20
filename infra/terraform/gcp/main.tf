# Status (20 Nov 2026): the resources that existed before this PR are APPLIED.
# Everything this PR adds or changes is ONLY WRITTEN until it goes through
# docs/RUNBOOK-gke.md. ADR-015 explains the capacity and cost decisions.

# --- Required APIs ----------------------------------------------------------

resource "google_project_service" "servicios" {
  for_each = toset([
    "container.googleapis.com",
    "artifactregistry.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
  ])
  service            = each.key
  disable_on_destroy = false
}

# --- Image registry ---------------------------------------------------------

resource "google_artifact_registry_repository" "cv_server" {
  location      = var.region
  repository_id = "cv-server"
  format        = "DOCKER"
  description   = "Imágenes de cv-server"

  # A pushed tag can never be moved: `:<sha>` always means the same image.
  docker_config {
    immutable_tags = true
  }

  depends_on = [google_project_service.servicios]
}

# --- Kubernetes cluster -----------------------------------------------------

resource "google_container_cluster" "cv_server" {
  name     = var.cluster_name
  location = var.zone # zonal: covered by the GKE free tier (one zonal cluster)

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

  # Add-ons. Every block is explicit so the plan shows exactly what is on.
  addons_config {
    # Kept: a later move from ingress-nginx to the GKE Gateway API needs it.
    http_load_balancing {
      disabled = false
    }
    horizontal_pod_autoscaling {
      disabled = false
    }
    dns_cache_config {
      enabled = true
    }
    gce_persistent_disk_csi_driver_config {
      enabled = true
    }
    # Off: nothing uses Filestore; it requested ~170 MiB per node plus a controller.
    gcp_filestore_csi_driver_config {
      enabled = false
    }
    # Step 1 of 2 to enforce NetworkPolicy (Calico). See variables.tf.
    network_policy_config {
      disabled = !var.network_policy_addon
    }
  }

  # Step 2 of 2: enforcement. GKE recreates the nodes when this changes.
  network_policy {
    enabled  = var.network_policy_enforced
    provider = var.network_policy_enforced ? "CALICO" : "PROVIDER_UNSPECIFIED"
  }

  # System metrics only. Managed Prometheus and the kube-state-metrics packages
  # (pods, deployments, HPA...) had no consumer and requested ~330 MiB.
  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS"]
    managed_prometheus {
      enabled = false
    }
  }

  logging_config {
    enable_components = ["SYSTEM_COMPONENTS", "WORKLOADS"]
  }

  # Provider-side guard (no API call): `terraform destroy` refuses until it is
  # set to false on purpose.
  deletion_protection = true

  depends_on = [google_project_service.servicios]

  lifecycle {
    precondition {
      condition     = !var.network_policy_enforced || var.network_policy_addon
      error_message = "network_policy_enforced needs network_policy_addon = true applied first."
    }
  }
}

# --- Node pools ---------------------------------------------------------------
#
# `general` replaces `principal`. Machine type and service account cannot be
# changed in place on a node pool, so the swap is blue/green: create `general`,
# drain `principal`, then set legacy_pool_enabled = false (RUNBOOK phase 2).

resource "google_container_node_pool" "general" {
  name     = "general"
  location = var.zone
  cluster  = google_container_cluster.cv_server.name

  initial_node_count = var.pool_min_nodes

  autoscaling {
    min_node_count = var.pool_min_nodes
    max_node_count = var.pool_max_nodes
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  # Upgrades add one node first and only then drain an old one (with the PDB).
  upgrade_settings {
    strategy        = "SURGE"
    max_surge       = 1
    max_unavailable = 0
  }

  node_config {
    machine_type = var.pool_machine_type
    spot         = true
    disk_type    = "pd-balanced"
    disk_size_gb = var.pool_disk_size_gb

    # Dedicated least-privilege identity instead of the Compute Engine default
    # service account (Editor on the project). Access is then decided by IAM,
    # so the broad scope is the one Google recommends with a custom SA.
    service_account = google_service_account.nodos.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]

    labels = {
      env = var.env
    }

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }
  }

  lifecycle {
    # The autoscaler owns the size after creation.
    ignore_changes = [initial_node_count]
  }

  depends_on = [
    google_project_iam_member.nodos,
    google_artifact_registry_repository_iam_member.nodos_pull,
  ]
}

# The pool applied on 19 Nov 2026 (2 x e2-small spot, default compute SA).
# Unchanged on purpose; deleted by setting legacy_pool_enabled = false.
resource "google_container_node_pool" "principal" {
  count = var.legacy_pool_enabled ? 1 : 0

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
    spot         = true
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]

    labels = {
      env = var.env
    }

    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }

  lifecycle {
    ignore_changes = [node_count]
  }
}

moved {
  from = google_container_node_pool.principal
  to   = google_container_node_pool.principal[0]
}
