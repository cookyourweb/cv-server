variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "Region for Artifact Registry, Secret Manager and Cloud SQL"
  type        = string
  default     = "europe-west1"
}

variable "zone" {
  description = "Cluster zone (zonal = cheaper)"
  type        = string
  default     = "europe-west1-b"
}

variable "env" {
  description = "Environment label"
  type        = string
  default     = "dev"
}

variable "cluster_name" {
  description = "GKE cluster name"
  type        = string
  default     = "cv-server-cluster"
}

variable "app_namespace" {
  description = "Kubernetes namespace of the cv-server release"
  type        = string
  default     = "default"
}

# --- `general` pool (target state, ADR-015) ----------------------------------

variable "pool_machine_type" {
  description = "Machine type of the general pool. e2-medium: 4 GB, ~2.9 GiB allocatable"
  type        = string
  default     = "e2-medium"
}

variable "pool_min_nodes" {
  description = "Minimum nodes: 2, so a spot preemption never takes both replicas"
  type        = number
  default     = 2
}

variable "pool_max_nodes" {
  description = "Maximum nodes for the autoscaler (a third node only while needed)"
  type        = number
  default     = 3
}

variable "pool_disk_size_gb" {
  description = "Boot disk per node. The live pool uses the 100 GB default; 30 GB is plenty for one image"
  type        = number
  default     = 30
}

# --- Legacy `principal` pool (applied 19 Nov 2026) ---------------------------
# Kept identical so the plan shows no change to it until it is removed.

variable "legacy_pool_enabled" {
  description = "Keep the old e2-small pool. Set to false after draining it (RUNBOOK phase 2)"
  type        = bool
  default     = true
}

variable "node_count" {
  description = "Legacy pool: initial nodes"
  type        = number
  default     = 1
}

variable "max_node_count" {
  description = "Legacy pool: autoscaler maximum"
  type        = number
  default     = 3
}

variable "machine_type" {
  description = "Legacy pool: machine type"
  type        = string
  default     = "e2-small"
}

# --- NetworkPolicy enforcement (Calico), two applies -------------------------

variable "network_policy_addon" {
  description = "Step 1: install the NetworkPolicy add-on (no node recreation)"
  type        = bool
  default     = false
}

variable "network_policy_enforced" {
  description = "Step 2: enforce NetworkPolicy with Calico. GKE recreates the nodes, one at a time"
  type        = bool
  default     = false
}

# --- Cloud SQL (unused, see cloudsql.tf) -------------------------------------

variable "cloud_sql_enabled" {
  description = "Keep the unused Cloud SQL instance. Proposed: false (RUNBOOK phase 6)"
  type        = bool
  default     = true
}

variable "db_tier" {
  description = "Cloud SQL tier (db-f1-micro is the cheapest)"
  type        = string
  default     = "db-f1-micro"
}
