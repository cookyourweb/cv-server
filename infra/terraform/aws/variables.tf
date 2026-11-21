variable "region" {
  description = "Región de AWS (us-east-1 es la más barata)"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Nombre del proyecto (se usa como prefijo de recursos)"
  type        = string
  default     = "cv-server"
}

variable "env" {
  description = "Etiqueta de entorno"
  type        = string
  default     = "demo"
}

variable "node_instance_type" {
  description = "Tipo de instancia de los nodos (t3.small es barato)"
  type        = string
  default     = "t3.small"
}

variable "db_instance_class" {
  description = "Clase de la instancia RDS (db.t3.micro es la más barata)"
  type        = string
  default     = "db.t3.micro"
}

variable "db_password" {
  description = "Contraseña de la base de datos (usar variable de entorno TF_VAR_db_password)"
  type        = string
  sensitive   = true
}

variable "cluster_name" {
  description = "Nombre del cluster EKS"
  type        = string
  default     = "cv-server-cluster"
}
