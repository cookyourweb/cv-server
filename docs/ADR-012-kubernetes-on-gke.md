# ADR-012: Run cv-server on GKE with Helm, keyless CI/CD and one env Secret, while Render keeps production traffic

**Status:** Accepted · 19 Nov 2026
**Scope:** `cv-server`, `helm/cv-server-chart`, `helm/cargar-entorno-gke.sh`, `.github/workflows/deploy.yml`, `infra/terraform/gcp`, `infra/terraform/aws`

> **For whoever picks this up (person or AI):** GKE is a second, fully configured home for the
> API. It does NOT receive user traffic until the panel's `urlApi` change (panel-empleo PR #3)
> is merged. Render stays the production host until then. Do not claim otherwise.

> **Partly superseded (20 Nov 2026), once the hardening PR is applied** (until then this ADR
> describes what runs):
> decision 5, the hand-made `cv-env` Secret, becomes the fallback of [ADR-014](ADR-014-secrets-external-secrets.md);
> decision 6, deploys, is tightened by [ADR-013](ADR-013-one-source-of-deploys.md);
> decision 7, `maxSurge: 0`, is replaced by 2 replicas + PDB + surge on bigger nodes ([ADR-015](ADR-015-gke-capacity-and-cost.md)).
> Two facts found later: the chart's Service was `type: LoadBalancer`, a second public IP
> serving plain HTTP next to the TLS ingress. And no CI deploy ever succeeded: every revision
> came from a laptop, and both CI runs failed on a missing `gke-gcloud-auth-plugin`.

---

## Context

The API ran only on Render, as a single managed service. I wanted the same service running
the way larger teams run it: containers, an orchestrator, infrastructure as code and a
pipeline that deploys without long-lived credentials. I also wanted to be able to explain
every piece and every failure.

## Decision

1. **Infrastructure as code with Terraform** (`infra/terraform/gcp`, applied). It creates a zonal
   GKE cluster, its own node pool (spot `e2-small` nodes with autoscaling, auto-repair and
   auto-upgrade), the Artifact Registry repository and the required APIs. The state stays out
   of git. `infra/terraform/aws` models the same architecture on EKS. It is validated but **not
   applied**.
2. **Helm chart** (`helm/cv-server-chart`). It holds the Deployment, the Service and the HPA
   (1-5 pods at 70% CPU), with liveness and readiness probes on `/health`.
3. **Hardened pods.** They run as non-root (uid 1000) on a read-only root filesystem, with
   `/tmp` as an `emptyDir`, `drop: ["ALL"]` capabilities and no privilege escalation. CPU and
   memory have requests and limits.
4. **TLS at the edge.** An NGINX ingress serves `api.cookyourwebai.es` with a Let's Encrypt
   certificate that renews itself.
5. **Configuration from one Secret.** With `secrets.envFromSecret=cv-env`, the pod loads every
   variable from the `cv-env` Secret through `envFrom`. Those are the same variables Render
   has, created with `--from-env-file`. The chart then renders **no** explicit `env` entries,
   because an explicit entry wins over `envFrom` and would hide the real value.
   `helm/cargar-entorno-gke.sh` checks the required variables, and checks that CORS allows
   the panel, before it applies anything. It never prints values.
6. **Keyless CI/CD.** `deploy.yml` authenticates to GCP with **Workload Identity Federation**:
   GitHub's short-lived OIDC token is exchanged for temporary credentials. It then builds and
   pushes the image tagged with the commit SHA, runs `helm upgrade` and checks `/health` over
   HTTPS. No GCP key is stored in GitHub.
7. **Rollout fitted to the nodes.** `rollout.maxSurge: 0`, `maxUnavailable: 1`. The small nodes
   have about 95% of their memory requested by GKE system pods, so a surge pod never gets
   scheduled. Pods are replaced one at a time instead.

## Consequences

- Rollback is one command: `helm rollback cv-server <revision>`.
- GKE and Render share Neon, Notion and the LLM providers. The container does **not** run
  migrations on start, so a newer image cannot change the schema under Render.
- With `maxSurge: 0` there is a few seconds of downtime per deploy while there is one pod.
  That is fine with no user traffic; with real traffic, it needs `replicaCount: 2` or bigger nodes.
- It runs on GCP credits. A Cloud SQL instance created by Terraform is not used by the app,
  because the database is Neon. Remove it or use it.

## Incidents found while deploying (19 Nov 2026)

| Symptom | Root cause | Fix |
|---|---|---|
| `/clave-api` answered "authentication not configured" | The `cv-secrets` Secret held placeholders | Load the real variables into `cv-env` through `envFrom` |
| Rollout stuck, pods `Pending`, "Insufficient memory" | A surge pod needs room the nodes don't have | `maxSurge: 0` in the chart |
| Risk: broken `DATABASE_URL` | Render's `.env` export quotes some values, and `--from-env-file` keeps the quotes literally | Strip the outer quotes before creating the Secret |
| Risk: the next push to `main` brings the placeholders back | `deploy.yml` ran `helm upgrade` without `envFromSecret` | Pass `--set secrets.envFromSecret=cv-env` in the workflow |

## Verify

```bash
kubectl get pods -l app=cv-server                       # 1/1 Running
curl -s https://api.cookyourwebai.es/health              # 200
curl -s "https://api.cookyourwebai.es/clave-api"         # 401 "missing Authorization: Bearer" = auth is on
kubectl exec deploy/cv-server-cv-server -- id            # uid=1000
helm history cv-server                                   # revisions to roll back to
```
