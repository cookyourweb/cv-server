variable "project_id" {
  description = "ID del proyecto de GCP"
  type        = string
}

variable "region" {
  description = "Región para Artifact Registry y Cloud SQL"
  type        = string
  default     = "europe-west1"
}

variable "zone" {
  description = "Zona del cluster (zonal = más barato)"
  type        = string
  default     = "europe-west1-b"
}

variable "env" {
  description = "Etiqueta de entorno"
  type        = string
  default     = "dev"
}

variable "cluster_name" {
  description = "Nombre del cluster GKE"
  type        = string
  default     = "cv-server-cluster"
}

variable "node_count" {
  description = "Nodos iniciales"
  type        = number
  default     = 1
}

variable "max_node_count" {
  description = "Nodos máximos del autoscaler"
  type        = number
  default     = 3
}

variable "machine_type" {
  description = "Tipo de máquina de los nodos"
  type        = string
  default     = "e2-small"
}

variable "db_tier" {
  description = "Tier de Cloud SQL (db-f1-micro es el más barato)"
  type        = string
  default     = "db-f1-micro"
}
