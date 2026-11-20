# Infrastructure as code: cv-server on GCP

Terraform for the GKE cluster that serves `https://api.cookyourwebai.es` (project
`cv-server-portfolio`, zone `europe-west1-b`). Production user traffic is still on Render.

## Status, resource by resource (20 Nov 2026)

| Resource | Status |
|---|---|
| APIs, Artifact Registry `cv-server`, cluster `cv-server-cluster`, pool `principal` (2 x e2-small spot) | **APPLIED** 19 Nov 2026 |
| Cloud SQL `cv-server-db` | **APPLIED but UNUSED** (the app uses Neon). Removal proposed, not done: `cloudsql.tf` |
| GCS remote state, pinned provider `5.45.2`, committed lock file | **ONLY WRITTEN** (runbook phase 0) |
| Pool `general` (e2-medium spot, 30 GB disk, own node SA), drain and delete `principal` | **ONLY WRITTEN** (phase 2) |
| Filestore CSI, Managed Prometheus and kube-state-metrics off; immutable image tags | **ONLY WRITTEN** (phase 1) |
| NetworkPolicy enforcement (Calico) | **ONLY WRITTEN** (phase 5) |
| Secret Manager `cv-server-env` + reader GSA bound to one KSA | **ONLY WRITTEN** (phase 3) |

The ordered commands, expected output and rollback for each phase are in
[`docs/RUNBOOK-gke.md`](../../../docs/RUNBOOK-gke.md). Costs and capacity: [ADR-015](../../../docs/ADR-015-gke-capacity-and-cost.md).

## Files

| File | What |
|---|---|
| `versions.tf` | Terraform and provider pins, GCS backend |
| `main.tf` | APIs, registry, cluster (add-ons, monitoring, network policy), node pools |
| `iam.tf` | Least-privilege node service account |
| `secrets.tf` | Secret Manager secret (container only, no values) and its reader identity |
| `cloudsql.tf` | The unused Cloud SQL instance, behind `cloud_sql_enabled` |

## Design decisions

- **Zonal cluster.** One zonal cluster is covered by the GKE free tier; regional is not.
- **Own node pool**, default pool removed, autoscaling with auto-repair and auto-upgrade.
- **Spot nodes, at least 2.** Spot is about half the on-demand price here. Two nodes plus 2
  replicas and a PDB mean that one preemption does not take the API down.
- **Workload Identity everywhere.** No service-account keys exist: CI uses Workload Identity
  Federation and External Secrets uses GKE Workload Identity.
- **Deletion protection.** `deletion_protection = true` on the cluster (provider-side guard).
  It was `false` until this PR, and this README used to say the opposite.
- **Values never in state.** Terraform creates the Secret Manager secret, not its versions.

## CI checks

`.github/workflows/infra.yml` runs `terraform fmt -check`, `terraform init -backend=false`,
`terraform validate` and `tflint` (config in `../.tflint.hcl`) on every PR touching `infra/`.
CI never runs `plan` or `apply`: those need project credentials and stay manual, reviewed steps.

## Honest summary (for interviews)

> "I wrote and applied Terraform for a zonal GKE cluster with its own spot node pool and
> Artifact Registry, using Workload Identity instead of keys. Hardening it (remote state,
> least-privilege nodes, Secret Manager, network policy) is written, linted and validated
> in CI, and applied through a step-by-step runbook."

Only say the last part is applied once the runbook phases have been run.
