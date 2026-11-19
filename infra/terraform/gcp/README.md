# Infraestructura como código — cv-server (GCP)

Terraform que describe la infraestructura mínima para correr `cv-server` en GKE.
**Aplicado** (proyecto `cv-server-portfolio`, europe-west1-b): crea el cluster que
sirve `https://api.cookyourwebai.es`. El state vive fuera del repo; nunca se commitea.

## Qué crea

| Recurso | Para qué |
|---|---|
| `google_project_service` | Habilita GKE, Artifact Registry y Cloud SQL. |
| `google_artifact_registry_repository` | Registro privado donde se hace `docker push` de la imagen. |
| `google_container_cluster` + `node_pool` | Cluster GKE **zonal** con node pool aparte (el default se elimina). |
| `google_sql_database_instance` | Postgres para persistencia (futuro `PostgresSaver` del agente). |

## Decisiones de diseño (y por qué)

- **Cluster zonal, no regional.** Un cluster regional multiplica el coste del
  control plane. Para portfolio no aporta nada.
- **`remove_default_node_pool = true`.** El node pool por defecto no se puede
  configurar bien; se crea uno propio con autoscaling, `auto_repair` y
  `auto_upgrade`.
- **Nodos `spot`.** Hasta ~70% más baratos; aceptable porque el servicio tolera
  reinicios (2+ réplicas detrás de un Service).
- **Workload Identity (`GKE_METADATA`).** Los pods asumen una service account de
  GCP sin ficheros de credenciales. Es la alternativa correcta a meter claves.
- **`deletion_protection = true`** en cluster y base de datos: evita un
  `terraform destroy` accidental.
- **Backend GCS comentado.** El estado local no sirve para equipo/CI; se activa
  cuando exista el bucket.

## Uso

```bash
# 1. Autenticarse
gcloud auth application-default login

# 2. Configurar variables
cp terraform.tfvars.example terraform.tfvars   # y editar project_id

# 3. Validar sin crear nada
terraform init
terraform validate
terraform plan

# 4. Crear (⚠️ cuesta dinero)
terraform apply

# 5. Apuntar kubectl al cluster
terraform output -raw get_credentials_command | bash

# 6. Construir y subir la imagen
docker build -t "$(terraform output -raw artifact_registry_url)/cv-server:prod" ../cv-server
docker push "$(terraform output -raw artifact_registry_url)/cv-server:prod"

# 7. Desplegar con el chart de Helm
helm upgrade --install cv-server ../cv-server-helm/cv-server-chart -f ../cv-server-helm/cv-server-chart/values.prod.yaml \
  --set image.repository="$(terraform output -raw artifact_registry_url)/cv-server"

# 8. Destruir (⚠️ primero quitar deletion_protection)
terraform destroy
```

## Coste aproximado (dev)

- Control plane zonal de GKE: gratis (GCP cobra el regional).
- 1 nodo `e2-small` spot: ~5–10 €/mes.
- Cloud SQL `db-f1-micro`: ~8–10 €/mes.
- Artifact Registry: céntimos por GB.

Total orientativo: **< 25 €/mes** si se deja encendido; se puede parar/destruir.

## Honestidad (para entrevista)

> "I wrote the Terraform for my service's infrastructure: a zonal GKE cluster
> with a dedicated autoscaling node pool, Artifact Registry, and Cloud SQL,
> using Workload Identity instead of service-account keys. I validated it with
> `terraform validate` and `plan`; I have not run it at production scale."

## Pendiente

- `terraform init/validate/plan` requieren Terraform y credenciales de GCP.
- Módulo remoto / workspaces por entorno si crece.
- Añadir `google_sql_user` + password en Secret Manager (nunca en estado plano).
