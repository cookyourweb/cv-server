# ADR-015: Capacity for 2 replicas, a PDB and surge deploys: e2-medium spot nodes, trimmed add-ons

**Status:** Accepted, ONLY WRITTEN (20 Nov 2026). Applied through `docs/RUNBOOK-gke.md`, phases 1, 2 and 5.
**Scope:** `infra/terraform/gcp/main.tf`, `variables.tf`, `iam.tf`

## Context: measured on 20 Nov 2026 (read-only `kubectl`/`gcloud`)

| Node (e2-small spot) | Allocatable memory | Memory requested | Memory used (`kubectl top`) | CPU requested |
|---|---|---|---|---|
| `...-tt6n` | 1358 MiB | 1327 MiB (97%) | 1351 MiB (99%) | 737m of 940m (78%) |
| `...-wq7w` | 1358 MiB | 1289 MiB (94%) | 1416 MiB (104%) | 733m of 940m (77%) |

The autoscaler is at its maximum (2). The cv-server pod requests 128 MiB/100m and uses about
104 MiB. GKE system pods take most of each node: fluentbit 230 MiB, metrics agent 145 MiB,
metadata server 100 MiB... So a surge pod never schedules (hence `maxSurge: 0`, with a few
seconds of downtime per deploy), and there is no room for a second replica. A PDB would only
block drains.

Unused managed add-ons that request memory:

| Add-on | Requested | Used by cv-server? |
|---|---|---|
| Filestore CSI (`filestore-node` x2 + lock controller) | about 360 MiB | No (no Filestore volumes) |
| Managed Prometheus (`collector` x2 + operator) | about 85 MiB requested, about 230 MiB used | No consumer |
| kube-state-metrics packages (`gke-managed-cim`) | about 130 MiB | No consumer |

## Decision

1. **Turn off** Filestore CSI, Managed Prometheus and the kube-state-metrics packages
   (system metrics and Cloud Logging stay on). That frees about 570 MiB of requests, at no cost.
2. **Replace the pool** with `general`: **2 to 3 x e2-medium spot** (4 GB, roughly 2.8-2.9 GiB
   allocatable by GKE's reservation formula), with a **30 GB** pd-balanced boot disk instead of
   the 100 GB default, and a least-privilege node service account. The swap is blue/green: both
   the machine type and the service account force a new pool.
3. **Chart:** 2 replicas minimum, PDB `minAvailable: 1`, `maxSurge: 1 / maxUnavailable: 0`, and
   a soft spread across nodes. With 2 nodes, one spot preemption leaves one replica serving.

## Cost (list prices, europe-west1, Cloud Billing catalog API, 20 Nov 2026, 730 h/month, USD)

Spot E2: 0.01223/vCPU-h and 0.001642/GiB-h. e2-small bills 0.5 vCPU + 2 GiB, e2-medium 1 vCPU + 4 GiB.
pd-balanced: 0.10/GiB-month.

| | Today (applied) | Target, 2 nodes | Target, 3rd node up |
|---|---|---|---|
| Nodes | 2 x e2-small spot = 13.72 | 2 x e2-medium spot = 27.45 | 41.17 |
| Boot disks | 2 x 100 GB = 20.00 | 2 x 30 GB = 6.00 | 9.00 |
| **Total** | **33.72** | **33.45 (delta -0.27)** | **50.17 (delta +16.45)** |

Unchanged on both sides: one zonal cluster's management fee is covered by the GKE free tier,
and the 2 load-balancer forwarding rules stay within the 5-rule minimum charge (0.025 USD/h).
The new Secret Manager secret costs at most about 0.06 USD/month.

Not included: **Cloud SQL `cv-server-db`, unused, about 9.37 USD/month** (0.0105 USD/h +
10 GiB x 0.17). Removing it is proposed in `cloudsql.tf` and runbook phase 6, not done.
Spot prices change over time: these are list prices on 20 Nov 2026, not an invoice.

## Alternatives considered

| Option | Monthly | Why not |
|---|---|---|
| Keep 2 x e2-small, only trim add-ons | +0 | Leaves about 670 MiB requested headroom across both nodes, but real usage is already 99-104%. It also needs room for ESO and Calico. Too little margin, and evictions are likely. The trim is still part of the decision. |
| 3 x e2-small spot | about 20.6 + disks | Each node repeats about 640 MiB of DaemonSets. Per usable GiB it costs more than e2-medium. |
| e2-standard-2 spot | about 27.4 per node | Dedicated CPU that this service does not need. About twice the cost. |
| GKE Autopilot | billed per pod request | Needs a NEW cluster and a migration. Worth a look later, out of scope here. |

## Risk: CPU, not memory, is the next limit

Shared-core e2-medium nodes have about the **same allocatable CPU as e2-small (about 940m)**.
After the trim, the estimate is about 1.5 vCPU requested of 1.88 (80%) on 2 nodes, and
about 1.6 (85%) while a surge pod exists. That includes the second API replica, ESO and a
second ingress-nginx controller. It is **before Calico**, whose requests will only be known
once it is enabled. The autoscaler can
add the third node (+16.72 USD/month while it runs). The runbook measures `kubectl describe
nodes` after phases 2 and 5. If 2 nodes stay above about 85% CPU requested, lower the cv-server
CPU request (it uses about 3m idle) before accepting a permanent third node.
