output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value     = module.eks.cluster_endpoint
  sensitive = true
}

output "get_credentials_command" {
  value = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.cv_server.repository_url
}

output "db_endpoint" {
  value = aws_db_instance.postgres.endpoint
}

output "db_connection_string" {
  value     = "postgresql://cvserver:${var.db_password}@${aws_db_instance.postgres.endpoint}/cvserver"
  sensitive = true
}
