# Runbook: switch the GKE environment off and on again

**State on 20 Nov 2026: OFF.** The cluster was validated end to end (see [evidence](evidence/gke-2026-11-20.md)), then switched off to stop paying for it. Production traffic runs on Render.

## What "off" means (reversible, nothing destroyed)

| Resource | State | Cost while off |
|---|---|---|
| GKE cluster `cv-server-cluster` (europe-west1-b) | Exists, **0 nodes**, node autoscaling disabled | 0 (the free tier covers one zonal control plane) |
| Helm releases `cv-server`, `ingress-nginx` | **Uninstalled**, so both load balancers are released | 0 |
| Helm release `cert-manager` + ClusterIssuer `letsencrypt-prod` | Kept | 0 (no pods without nodes) |
| Ingress `cv-server-ingress` (host `api.cookyourwebai.es`, TLS secret `cv-server-tls`) | Kept | 0 |
| Secret `cv-env` (the ~29 production variables) | Kept in the cluster | 0 |
| Cloud SQL `cv-server-db` | **Stopped** (activation policy NEVER); the app does not use it, the DB is Neon | ~2 €/month (storage) |
| Artifact Registry images `814a90b`, `0213a2f`, `latest` | Kept | cents |

Expected total while off: **about 2 €/month**. Running, it was about 2.5 €/day.

Check that nothing billable is running:
```bash
gcloud compute instances list --project cv-server-portfolio          # empty
gcloud compute forwarding-rules list --project cv-server-portfolio   # empty
gcloud sql instances list --project cv-server-portfolio              # cv-server-db  STOPPED
```

## Switch it ON (about 15 minutes)

```bash
# 1. Nodes back (2 x spot e2-small) and autoscaling as before (1-2)
gcloud container clusters resize cv-server-cluster --node-pool principal --num-nodes 2 \
  --zone europe-west1-b --project cv-server-portfolio --quiet
gcloud container clusters update cv-server-cluster --node-pool principal \
  --enable-autoscaling --min-nodes 1 --max-nodes 2 \
  --zone europe-west1-b --project cv-server-portfolio --quiet
kubectl get nodes                                                   # 2 Ready

# 2. Ingress controller: creates a NEW public IP
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx && helm repo update
helm install ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx --create-namespace
kubectl get svc ingress-nginx-controller -n ingress-nginx -w        # wait for EXTERNAL-IP

# 3. DNS: point the A record of api.cookyourwebai.es to that new IP (it was 34.52.235.136)

# 4. The app, from THIS chart (not from a branch without envFromSecret: that deploys placeholders)
kubectl get secret cv-env                                           # must exist; if not, see "Secrets"
helm install cv-server ./helm/cv-server-chart \
  --set image.repository=europe-west1-docker.pkg.dev/cv-server-portfolio/cv-server/cv-server \
  --set image.tag=0213a2f --set image.pullPolicy=Always \
  --set service.type=ClusterIP \
  --set secrets.envFromSecret=cv-env
kubectl rollout status deployment/cv-server-cv-server

# 5. Verify (cert-manager reissues the certificate once DNS points to the new IP)
curl -s -o /dev/null -w "%{http_code}\n" https://api.cookyourwebai.es/health          # 200
curl -s https://api.cookyourwebai.es/clave-api   # 401 "missing Authorization: Bearer" = auth is on
```

`service.type=ClusterIP` on purpose: before 20 Nov the Service was also a public **LoadBalancer**. It was a second load balancer (about 18 €/month) serving plain HTTP that bypassed TLS. The ingress is the only door.

### Secrets
If `cv-env` is missing: in Render, open cv-server → Environment → **Export → .env**. Save the file **outside the Desktop** with `chmod 600`, then run `./helm/cargar-entorno-gke.sh <file>`. Delete the file afterwards. The export wraps some values in quotes (`DATABASE_URL`, `CV_CLAVES`), and the script expects them without quotes: strip the outer quotes first.

## Switch it OFF again

```bash
helm uninstall cv-server
helm uninstall ingress-nginx -n ingress-nginx
gcloud compute forwarding-rules list --project cv-server-portfolio   # wait until empty
gcloud container clusters update cv-server-cluster --node-pool principal --no-enable-autoscaling \
  --zone europe-west1-b --project cv-server-portfolio --quiet
gcloud container clusters resize cv-server-cluster --node-pool principal --num-nodes 0 \
  --zone europe-west1-b --project cv-server-portfolio --quiet
```
Disable autoscaling **before** resizing to 0, or the autoscaler creates the nodes again (it happened on 20 Nov).

## Things to remember
- `deploy.yml` runs on every push to `main`. While the cluster is off it fails, as it has always failed: the runner lacks `gke-gcloud-auth-plugin` (fixed in PR #12).
- The panel's `urlApi` change to `api.cookyourwebai.es` (panel-empleo PR #3) must **not** reach production while GKE is off. Point it back to Render, or switch GKE on first.
- Hardening for real traffic (2 replicas + PDB, Secret Manager, NetworkPolicy, full-SHA tags): PR #12 and `docs/RUNBOOK-gke.md` there.

## Same architecture on AWS (EKS)
`infra/terraform/aws` is validated but never applied. It can run in the demo account a family member lent (`741973714432`, eu-central-1) once its IAM Identity Center MFA issue is solved:
1. Sign in (SSO) and open **CloudShell** in eu-central-1. There's no need to install the AWS CLI on the Mac.
2. Create the state bucket `cv-server-terraform-state-741973714432-eu-central-1` (versioning, encryption, public access blocked).
3. `terraform init && terraform apply` in `infra/terraform/aws` → push the image to ECR → `helm install` with `values` for EKS.
4. Demo, capture the evidence (as in `docs/evidence/`), then **`terraform destroy` the same day**. EKS + NAT + RDS cost about 5-6 $/day.
