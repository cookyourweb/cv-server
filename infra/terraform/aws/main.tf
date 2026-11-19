terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

# --- VPC (red privada) -----------------------------------------------------

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.project_name}-vpc"
  cidr = "10.0.0.0/16"

  azs             = ["${var.region}a", "${var.region}b"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24"]

  enable_nat_gateway   = true
  single_nat_gateway   = true # 1 NAT para ahorrar (~$32/mes en vez de $64)
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    env = var.env
  }
}

# --- ECR (registro de imágenes) -------------------------------------------

resource "aws_ecr_repository" "cv_server" {
  name                 = "cv-server"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    env = var.env
  }
}

# --- EKS (cluster de Kubernetes) -------------------------------------------

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = "1.30"

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Control plane gestionado por AWS ($73/mes)
  cluster_endpoint_public_access = true

  # IRSA: los pods asumen roles de IAM sin claves
  enable_irsa = true

  eks_managed_node_groups = {
    principal = {
      min_size     = 1
      max_size     = 2
      desired_size = 1

      instance_types = [var.node_instance_type]
      capacity_type  = "SPOT" # abarata ~70%

      labels = {
        env = var.env
      }
    }
  }

  tags = {
    env = var.env
  }
}

# --- RDS (PostgreSQL) ------------------------------------------------------

resource "aws_db_subnet_group" "cv_server" {
  name       = "${var.project_name}-db-subnet"
  subnet_ids = module.vpc.private_subnets

  tags = {
    env = var.env
  }
}

resource "aws_db_instance" "postgres" {
  identifier     = "${var.project_name}-db"
  engine         = "postgres"
  engine_version = "15"
  instance_class = var.db_instance_class

  allocated_storage     = 20
  max_allocated_storage = 50
  storage_type          = "gp2"

  db_name  = "cvserver"
  username = "cvserver"
  password = var.db_password

  vpc_security_group_ids = [aws_security_group.db.id]
  db_subnet_group_name   = aws_db_subnet_group.cv_server.name

  skip_final_snapshot = true # para demo/portfolio (en prod: false)
  deletion_protection = false

  tags = {
    env = var.env
  }
}

# --- Security Group para la DB ---------------------------------------------

resource "aws_security_group" "db" {
  name_prefix = "${var.project_name}-db-"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [module.vpc.vpc_cidr_block]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    env = var.env
  }
}
