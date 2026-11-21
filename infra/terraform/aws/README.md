# Infraestructura como código — cv-server (AWS)

Terraform que describe la infraestructura mínima para correr `cv-server` en EKS.
**No aplicado**: requiere cuenta de AWS con facturación. Es evidencia de que sé
modelar infraestructura como código en múltiples clouds, no un despliegue en producción.

## Qué crea

| Recurso | Para qué |
|---|---|
| `module "vpc"` | VPC con subnets públicas y privadas, 1 NAT Gateway (ahorro). |
| `aws_ecr_repository` | Registro privado donde se hace `docker push` de la imagen. |
| `module "eks"` | Cluster EKS con node group gestionado (spot, autoscaling). |
| `aws_db_instance` | Postgres en RDS para persistencia (futuro `PostgresSaver`). |
| `aws_security_group` | Firewall para la DB (solo acceso desde la VPC). |

## Decisiones de diseño (y por qué)

- **VPC con 1 NAT Gateway.** Un NAT por AZ cuesta el doble. Para portfolio/desmo, 1 basta.
- **Nodos `spot`.** Hasta ~70% más baratos; aceptable porque el servicio tolera reinicios.
- **IRSA (IAM Roles for Service Accounts).** Los pods asumen roles de IAM sin ficheros de credenciales. Equivalente a Workload Identity en GCP.
- **RDS `db.t3.micro` + `skip_final_snapshot = true`.** El más barato y sin snapshot final (para demo). En prod: `db.t3.small` + snapshot.
- **`deletion_protection = false`.** Para poder hacer `terraform destroy` sin fricción (demo/portfolio).
- **Backend S3 comentado.** El estado local no sirve para equipo/CI; se activa cuando exista el bucket.

## Uso

```bash
# 1. Autenticarse
aws configure  # Access Key + Secret Key

# 2. Configurar variables
cp terraform.tfvars.example terraform.tfvars   # y editar db_password

# 3. Validar sin crear nada
terraform init
terraform validate
terraform plan

# 4. Crear (⚠️ cuesta dinero: ~$4/día)
export TF_VAR_db_password="tu_password_segura"
terraform apply

# 5. Apuntar kubectl al cluster
terraform output -raw get_credentials_command | bash

# 6. Construir y subir la imagen
docker build -t "$(terraform output -raw ecr_repository_url):latest" ../cv-server
docker push "$(terraform output -raw ecr_repository_url):latest"

# 7. Desplegar con el chart de Helm
helm upgrade --install cv-server ../cv-server-helm/cv-server-chart \
  --set image.repository="$(terraform output -raw ecr_repository_url)" \
  --set image.tag=latest

# 8. Destruir (⚠️ primero quitar deletion_protection si se activó)
terraform destroy
```

## Coste aproximado (demo)

- EKS control plane: $73/mes (~$2.43/día).
- 1 nodo `t3.small` spot: ~$4/mes.
- RDS `db.t3.micro`: ~$15/mes.
- NAT Gateway: ~$32/mes.
- LoadBalancer: ~$18/mes.
- ECR: céntimos por GB.

Total orientativo: **~$4/día** si se deja encendido; se puede destruir.

## Honestidad (para entrevista)

> "I wrote Terraform for my service's infrastructure on AWS: an EKS cluster with
> a managed spot node group, ECR, RDS Postgres, and a VPC with IRSA. I validated
> it with `terraform validate` and `plan`. I have not run it at production scale.
> The same application also runs on GCP (GKE), so I can compare both providers."

## Pendiente

- `terraform init/validate/plan` requieren Terraform y credenciales de AWS.
- Módulo remoto / workspaces por entorno si crece.
- Añadir `aws_secretsmanager_secret` para la DB password (nunca en estado plano).
- Adaptar el chart de Helm para usar IRSA en vez de secretKeyRef.
