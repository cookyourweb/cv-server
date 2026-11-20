# ADR-014: App config from GCP Secret Manager through External Secrets Operator

**Status:** Accepted, ONLY WRITTEN (20 Nov 2026). Applied through `docs/RUNBOOK-gke.md`, phase 3.
**Scope:** `infra/terraform/gcp/secrets.tf`, `helm/cv-server-chart/templates/externalsecret.yaml`, `infra/k8s/platform/`, `infra/secrets/`

## Context

The pod reads about 45 variables through `envFrom` from the Secret `cv-env`, typed in by hand
from a `.env` file on a laptop (`helm/cargar-entorno-gke.sh`). That means no audit trail, no
version history and no rotation story. The cluster cannot be rebuilt without that file. The app
reads its config from **environment variables** and this task must not change app code.

## Decision

**External Secrets Operator (ESO) 2.15.0**, syncing one JSON secret in Secret Manager into a
Kubernetes Secret.

```
Secret Manager: cv-server-env (JSON, one key per variable, versioned, audit-logged)
   │  read by GSA cv-server-secrets  (secretAccessor on THIS secret only)
   │  impersonated via Workload Identity by KSA default/cv-server-secrets (no pod runs as it)
   ▼
ESO SecretStore + ExternalSecret (namespaced, rendered by the chart)
   ▼
Kubernetes Secret cv-env-sm  ──envFrom──▶  cv-server pods (unchanged contract)
```

- Values reach Secret Manager through `infra/secrets/subir-a-secret-manager.sh`, a pipe from
  `entorno.py` to `gcloud`. They never pass through Terraform state, Helm values, git or CI logs.
- `cv-env` (the hand-made Secret) stays as the documented fallback. Switching back is one value.

## Why ESO and not the Secret Manager CSI driver

| | ESO (chosen) | GKE Secret Manager add-on (CSI) |
|---|---|---|
| How the app gets values | Kubernetes Secret, so `envFrom` works unchanged | Files mounted in the pod: the app would have to read files, which is an **app change** |
| Extra pods | 3 small Deployments (about 128 MiB requested in total) | A node DaemonSet, managed by Google |
| Who operates it | Us: a pinned Helm chart | Google |
| Value at rest in the cluster | Yes, as a Secret in etcd (GKE encrypts etcd at rest) | No Kubernetes Secret, unless the optional sync is used |

The CSI driver keeps values out of etcd, which is better. It still loses here because it breaks
the env-var contract, and keeping that contract is a hard constraint of this task. If the app
learns to read files, revisit this decision.

## Consequences

- One more operator to keep up to date. The version is pinned in `infra/k8s/platform/versions.env`.
  The CRD schemas in `helm/schemas` must follow it.
- **Rotation:** add a new version, force a sync, then `kubectl rollout restart`. Pods read env
  only at start. A reloader was not added because, for one service, the restart is one command.
- One JSON secret costs about 0.06 USD/month per active version (often inside the free tier).
  The trade-off: every rotation re-uploads the whole set. Splitting the most sensitive keys into
  their own secrets is a later, optional step.
- Optional hardening not done: Cloud KMS application-layer encryption of Secrets in etcd.
