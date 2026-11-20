# RUNBOOK: applying the GKE hardening (cv-server)

**State when written (20 Nov 2026):** none of this is applied. The live cluster is the one
described in ADR-012: Helm revision 5, image `:814a90b`, 1 replica, 2 x e2-small spot nodes.
Production user traffic is on **Render**, so a few seconds of GKE downtime affect nobody. Still,
every phase below is designed to need none.

Each phase has: **do**, **expected output**, **verify** and **roll back**. Do not start a phase
until the previous one verifies. If any output differs from the expected one, **stop**: do
not "fix it forward" in the cluster by hand.

Never print secret values. Every command here prints names, counts or statuses only.

| Phase | What | Changes infra | Before or after merging the PR |
|---|---|---|---|
| 0 | Tools, remote state | GCS bucket | before |
| 1 | Terraform: new pool, node SA, Secret Manager, add-on trim | yes | before |
| 2 | Platform: External Secrets, ingress log redaction | yes | before |
| 3 | Load the env into Secret Manager | secret version | before |
| 4 | Adopt the Ingress, merge, CI deploys the new chart | yes | **merge here** |
| 5 | Drain and delete the old e2-small pool | yes | after |
| 6 | Pod Security Admission `restricted` | yes | after |
| 7 | NetworkPolicy enforcement (Calico) | yes, node recreation | after |
| 8 | (Proposal) delete the unused Cloud SQL | yes, destructive | after, optional |

---

## Phase 0: prerequisites and remote state

### 0.1 Tools (versions used to validate this PR)

```bash
terraform version          # Terraform v1.9.8 (any 1.9+ < 2 is accepted)
helm version --short       # v3.22.1  <- REQUIRED for helm-diff 3.15.15
helm plugin install https://github.com/databus23/helm-diff --version v3.15.15
helm plugin list           # diff  3.15.15
kubectl config current-context
# gke_cv-server-portfolio_europe-west1-b_cv-server-cluster
gcloud config get-value project   # cv-server-portfolio
```

Why Helm 3.22.1: on 20 Nov, the laptop's Helm 3.16.3 refused to load helm-diff 3.15.15
(`unknown field "platformHooks"`). Helm 3.22.1 with helm-diff 3.15.15 was verified to work.

### 0.2 Merge the SSE fix first

`fix/sse-user-from-token` (814a90b) is what runs on GKE today, but it exists only on the
laptop. The first CI deploy from `main` (phase 4) replaces it with whatever `main` contains.
Push it, open its PR and merge it into `main` **before phase 4**, or accept that GKE loses the fix.

### 0.3 State bucket (once)

```bash
gcloud storage buckets create gs://cv-server-portfolio-tfstate \
  --project cv-server-portfolio --location europe-west1 \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://cv-server-portfolio-tfstate --versioning
gcloud storage buckets describe gs://cv-server-portfolio-tfstate \
  --format='value(versioning_enabled,public_access_prevention)'
```

Expected: `True    enforced`.

### 0.4 Move the applied state into the bucket

```bash
cd infra/terraform/gcp
cp ../../../../cv-server-terraform/terraform.tfvars .   # gitignored; adjust the path to yours
terraform init                                            # backend "gcs", empty
terraform state list | wc -l                              # 0
terraform state push ../../../../cv-server-terraform/terraform.tfstate
terraform state list
```

Expected: about 8 addresses, including `google_container_cluster.cv_server`,
`google_container_node_pool.principal` and `google_sql_database_instance.postgres`.

**Check your terraform.tfvars:** if it sets `machine_type`, `node_count` or `max_node_count`,
keep those lines. They now apply only to the old pool, and keeping them guarantees the plan
does not touch it. The new pool uses the `pool_*` variables.

**Roll back:** the old local state at `../cv-server-terraform/terraform.tfstate` is
untouched. Delete the bucket objects and keep using the old directory.

---

## Phase 1: Terraform, additive and in-place changes

```bash
terraform plan -out=fase1.plan
```

**Expected plan (stop if it differs):**

```
  # google_container_node_pool.principal has moved to google_container_node_pool.principal[0]
  # google_sql_database_instance.postgres has moved to google_sql_database_instance.postgres[0]
  # google_sql_database.cv_server has moved to google_sql_database.cv_server[0]
  ~ google_container_cluster.cv_server             (update in-place: addons, monitoring, deletion_protection)
  ~ google_artifact_registry_repository.cv_server  (update in-place: docker_config.immutable_tags)
  + google_project_service.servicios["secretmanager.googleapis.com"]
  + google_service_account.nodos / google_project_iam_member.nodos[...] / ..._repository_iam_member.nodos_pull
  + google_container_node_pool.general
  + google_secret_manager_secret.cv_server_env
  + google_service_account.secretos / ..._secret_iam_member.secretos_lector / ..._iam_member.secretos_workload_identity
Plan: 9 to add, 2 to change, 0 to destroy.
```

`0 to destroy`, and **no** `must be replaced`, are mandatory. The `network_policy` block may
show as `enabled = false` / `PROVIDER_UNSPECIFIED`. That matches today and is not a change.

```bash
terraform apply fase1.plan        # about 10-15 min: the cluster update runs before the new pool
```

**Verify:**

```bash
kubectl get nodes -L cloud.google.com/gke-nodepool
# 2 x principal (e2-small) + 2 x general, all Ready
kubectl get ds -A | grep -E 'filestore|collector'          # nothing
kubectl get pods -n gke-managed-cim                        # No resources found (may take a few minutes)
kubectl describe nodes -l cloud.google.com/gke-nodepool=general | grep -A6 'Allocated resources'
gcloud artifacts repositories describe cv-server --location europe-west1 \
  --format='value(dockerConfig.immutableTags)'             # True
```

Write down the allocatable memory/CPU of a `general` node. ADR-015 estimates them at about
2.8-2.9 GiB and 940m.

**Roll back:** `git revert` the Terraform commit's settings you need (for example re-enable an
add-on), `plan`, `apply`. Deleting `general` is safe at this point: nothing runs only there.

---

## Phase 2: platform add-ons

```bash
infra/k8s/platform/instalar.sh diff  external-secrets   # only "has been added" lines
infra/k8s/platform/instalar.sh apply external-secrets   # type: external-secrets
kubectl label ns external-secrets pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/warn=restricted --overwrite --dry-run=server
# Expected: no "Warning:" lines; then run it again without --dry-run=server
kubectl -n external-secrets get pods
# external-secrets-xxx, -cert-controller-xxx, -webhook-xxx   1/1 Running
kubectl get crd externalsecrets.external-secrets.io -o jsonpath='{.spec.versions[*].name}'
# v1 v1beta1
```

ingress-nginx: access-log redaction (ADR-016), plus 2 controllers with a PDB. Without them,
draining a node in phase 5 or 7 evicts the only controller and the edge goes down, even
though the API has 2 replicas.

```bash
infra/k8s/platform/instalar.sh diff  ingress-nginx
# Expected (verified read-only on 20 Nov), exactly three changes:
#   ConfigMap ingress-nginx-controller   + log-format-upstream: "... $request_method $uri ..."
#   Deployment ingress-nginx-controller  replicas: 1 -> 2
#   PodDisruptionBudget ingress-nginx-controller has been added (minAvailable: 1)
infra/k8s/platform/instalar.sh apply ingress-nginx      # adds a controller; nginx reloads its config
kubectl -n ingress-nginx get pods -o wide               # 2 controllers Running, ideally on different nodes
curl -s -o /dev/null -w '%{http_code}\n' 'https://api.cookyourwebai.es/health?probe=redaction'
kubectl -n ingress-nginx logs deploy/ingress-nginx-controller --tail=5 | grep -c 'probe=redaction'
# Expected: 200, then 0 (the query string is no longer logged)
```

Optional exposure check (counts only, prints nothing sensitive):

```bash
gcloud logging read 'resource.type="k8s_container" AND textPayload:"progress?" AND textPayload:"token="' \
  --project cv-server-portfolio --freshness 30d --format='value(timestamp)' | wc -l
```

If that is above 0, assume the logged tokens were exposed. Google JWTs expire within an hour.
If `CLAVE_MAQUINA` was ever used on that route, **rotate it** (on Render and in Secret Manager).

**Roll back:** `helm -n external-secrets uninstall external-secrets` (nothing uses it yet);
`helm -n ingress-nginx rollback ingress-nginx 1`.

---

## Phase 3: load the env into Secret Manager

```bash
infra/secrets/subir-a-secret-manager.sh <path-to-render.env>
```

Expected:

```
NN variables:
  CLAUDE_API_KEY
  ...                                 (names only)
Add these variables as a new version of cv-server-env in cv-server-portfolio? Type 'yes': yes
New version: 1
```

It refuses (exit 1, names only) if a required variable is missing or empty, if a name is
duplicated, or if `CORS_ORIGENES` lacks `https://empleo.cookyourwebai.es`.

**Verify (names only):**

```bash
gcloud secrets versions list cv-server-env --project cv-server-portfolio --format='value(name,state)'
# 1   enabled
# Names in the live hand-made Secret, to compare in phase 4:
kubectl -n default get secret cv-env -o go-template='{{range $k, $v := .data}}{{$k}}{{"\n"}}{{end}}' | sort > /tmp/cv-env.names
wc -l < /tmp/cv-env.names
```

**Roll back:** `gcloud secrets versions disable 1 --secret cv-server-env`. Nothing reads it yet.

---

## Phase 4: adopt the Ingress, merge, deploy

### 4.1 Let Helm adopt the hand-made Ingress

Without this step, the deploy fails with `Ingress "cv-server-ingress" ... exists and cannot be
imported`. With `--atomic`, Helm then rolls back by itself, so nothing breaks, but nothing deploys either.

```bash
kubectl -n default label ingress cv-server-ingress app.kubernetes.io/managed-by=Helm --overwrite
kubectl -n default annotate ingress cv-server-ingress \
  meta.helm.sh/release-name=cv-server meta.helm.sh/release-namespace=default --overwrite
```

### 4.2 Preview what the deploy will change (read-only)

From a clean `main` checkout that contains this PR, after the image exists (or with the
current image `814a90b1e5688efd0d2fdb2e697f247fe8d51938` to preview the chart alone):

```bash
helm diff upgrade cv-server helm/cv-server-chart -n default \
  -f helm/cv-server-chart/values.gke.yaml --set image.tag=<full sha> --context 1 | grep '^default, '
```

Expected (ESO objects included):

```
default, cv-server-cv-server, Deployment (apps) has changed:        # surge 1/0, SA, seccomp, spread, envFrom cv-env-sm
default, cv-server-cv-server, Service (v1) has changed:             # LoadBalancer -> ClusterIP
default, cv-server-cv-server-hpa, HorizontalPodAutoscaler ... has changed:   # minReplicas 1 -> 2
default, cv-server, ServiceAccount (v1) has been added:
default, cv-server-secrets, ServiceAccount (v1) has been added:
default, cv-server-gcp-secret-manager, SecretStore ... has been added:
default, cv-server-env, ExternalSecret ... has been added:
default, cv-server-cv-server, PodDisruptionBudget (policy) has been added:
default, cv-server-{default-deny,allow,helm-test,acme-solver}, NetworkPolicy ... has been added:
default, cv-server-ingress, Ingress ... has changed:                # labels only, after 4.1
```

(Verified read-only on 20 Nov 2026 with ESO disabled: the same list without the ESO lines,
and with the Ingress as "added" because 4.1 had not been done.)

### 4.3 Merge

Merge order: the SSE fix (0.2), then PR #10, then this PR (or this PR into `infra/gke-real-config`
first, then #10). The push to `main` runs `tests`. When it passes, `deploy` builds, scans, pushes
`:<sha>` and runs `helm upgrade --atomic`.

```bash
gh run watch --repo cookyourweb/cv-server $(gh run list --repo cookyourweb/cv-server --workflow deploy.yml --limit 1 --json databaseId -q '.[0].databaseId')
```

If CI is unavailable: `helm/desplegar-manual.sh --dry-run`, then `helm/desplegar-manual.sh`.
It only works on a clean `main` equal to `origin/main` with an image CI already built.

**Verify:**

```bash
kubectl -n default get externalsecret cv-server-env
# NAME            STORETYPE     STORE                          REFRESH   STATUS         READY
# cv-server-env   SecretStore   cv-server-gcp-secret-manager   1h        SecretSynced   True
kubectl -n default get secret cv-env-sm -o go-template='{{range $k, $v := .data}}{{$k}}{{"\n"}}{{end}}' | sort | diff /tmp/cv-env.names - && echo "same variable names"
kubectl -n default get pods -l app=cv-server -o wide        # 2/2 Running, on two different nodes
kubectl -n default get pdb                                  # MIN AVAILABLE 1, ALLOWED DISRUPTIONS 1
kubectl -n default get svc cv-server-cv-server              # TYPE ClusterIP, no EXTERNAL-IP
helm test cv-server -n default --logs                       # GET /health -> 200 ... Phase: Succeeded
curl -s -o /dev/null -w '%{http_code}\n' https://api.cookyourwebai.es/health        # 200
curl -s -o /dev/null -w '%{http_code}\n' https://api.cookyourwebai.es/clave-api     # 401 (auth on)
curl -s -m 5 -o /dev/null -w '%{http_code}\n' http://34.156.161.218/health || echo "old LB IP gone"
```

**Zero-downtime check of the next deploy:** run this in a second terminal during any later deploy.

```bash
while true; do printf '%s ' "$(curl -s -o /dev/null -w '%{http_code}' https://api.cookyourwebai.es/health)"; sleep 0.5; done
# Expected: only 200s
```

**Roll back:**

- Bad release: `helm history cv-server -n default`, then `helm rollback cv-server <rev> -n default --wait`.
  Revision 5 is the pre-PR state. Rolling back to it brings back the LoadBalancer Service and 1 replica.
- ESO problem only: open a PR setting `secrets.envFromSecret: cv-env` and
  `externalSecrets.enabled: false` in `values.gke.yaml` (the hand-made Secret is still there),
  or, in an incident, roll back with Helm and merge that PR afterwards.
- After any `helm rollback`, `main` and the cluster differ until a fix is merged. Write it down.

---

## Phase 5: retire the old e2-small pool

```bash
for n in $(kubectl get nodes -l cloud.google.com/gke-nodepool=principal -o name); do kubectl cordon "$n"; done
kubectl get nodes -l cloud.google.com/gke-nodepool=principal -o name | head -1 | \
  xargs -I{} kubectl drain {} --ignore-daemonsets --delete-emptydir-data --timeout=5m
# Keep the curl loop from phase 4 running: only 200s. The PDB keeps one replica up.
kubectl -n default get pods -l app=cv-server -o wide     # both Running on general nodes
# Drain the second principal node the same way.
```

Then in `terraform.tfvars` set `legacy_pool_enabled = false`:

```bash
terraform plan -out=fase5.plan    # Expected: Plan: 0 to add, 0 to change, 1 to destroy (principal[0])
terraform apply fase5.plan
kubectl get nodes -L cloud.google.com/gke-nodepool        # only general nodes
kubectl describe nodes | grep -A6 'Allocated resources'    # note CPU %, see ADR-015
```

**Roll back:** before the apply, `kubectl uncordon` the principal nodes. After it, set
`legacy_pool_enabled = true` and apply. That creates a new e2-small pool.

---

## Phase 6: Pod Security Admission `restricted`

```bash
kubectl apply --dry-run=server -f infra/k8s/platform/namespaces.yaml
# Expected: no "Warning: existing pods in namespace ... violate" lines.
# If cv-server pods are listed, phase 4 has not deployed the new chart: stop.
kubectl apply -f infra/k8s/platform/namespaces.yaml
kubectl get ns default --show-labels | tr ',' '\n' | grep pod-security
helm test cv-server -n default --logs                     # still passes
```

The next Let's Encrypt renewal starts a cert-manager solver pod in `default`. cert-manager
v1.16 solver pods meet `restricted`. Confirm after the renewal date:
`kubectl get certificate -n default` stays `READY True`.

**Roll back:** `kubectl label ns default pod-security.kubernetes.io/enforce-`.

---

## Phase 7: enforce NetworkPolicy (Calico)

Two applies, because GKE needs the add-on before enforcement.

```bash
# terraform.tfvars: network_policy_addon = true
terraform plan -out=fase7a.plan   # Expected: 1 to change (cluster addons_config), 0 to destroy
terraform apply fase7a.plan

# terraform.tfvars: network_policy_enforced = true
terraform plan -out=fase7b.plan   # Expected: 1 to change (cluster network_policy), 0 to destroy
terraform apply fase7b.plan       # GKE recreates the nodes one at a time (surge 1); keep the curl loop running
```

**Verify:**

```bash
kubectl -n kube-system get pods -l k8s-app=calico-node      # one per node, Running
kubectl describe nodes | grep -A6 'Allocated resources'     # CPU: see ADR-015 risk section
helm test cv-server -n default --logs                       # allowed path: passes
curl -s -o /dev/null -w '%{http_code}\n' https://api.cookyourwebai.es/health        # 200 (ingress -> pod allowed)
# Denied path: a pod without the helm-test label must NOT reach the API.
kubectl -n default run np-check --rm -i --restart=Never \
  --image=europe-west1-docker.pkg.dev/cv-server-portfolio/cv-server/cv-server:<deployed sha> \
  --overrides='{"spec":{"automountServiceAccountToken":false,"securityContext":{"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"np-check","image":"europe-west1-docker.pkg.dev/cv-server-portfolio/cv-server/cv-server:<deployed sha>","command":["python","-c","import urllib.request;urllib.request.urlopen(\"http://cv-server-cv-server/health\",timeout=5)"],"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}}}]}}'
# Expected: a timeout error and a non-zero exit (blocked by cv-server-default-deny)
```

**Roll back:** set `network_policy_enforced = false` and apply (the nodes are recreated
again). Faster for a single bad rule: open a PR with `networkPolicy.enabled: false`. The
policies disappear and the default allow-all returns.

---

## Phase 8 (proposal): delete the unused Cloud SQL instance

Only if Vero decides. About 9.37 USD/month saved (ADR-015). The app uses Neon, and nothing
in the chart, the env or the code points at this instance.

```bash
gcloud sql instances describe cv-server-db --project cv-server-portfolio \
  --format='value(state,settings.backupConfiguration.enabled)'   # RUNNABLE  False
# terraform.tfvars: cloud_sql_enabled = false
terraform plan -out=fase8.plan    # Expected: 0 to add, 0 to change, 2 to destroy (instance + database)
terraform apply fase8.plan
```

**Roll back:** none for the data, because the instance is gone. Recreating an empty instance
is `cloud_sql_enabled = true` plus apply. That is why this phase is last and optional.
