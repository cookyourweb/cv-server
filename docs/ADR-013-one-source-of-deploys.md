# ADR-013: GKE deploys come from one place, tested main commits by SHA

**Status:** Accepted, ONLY WRITTEN (20 Nov 2026). It takes effect when this PR reaches `main`.
**Scope:** `.github/workflows/deploy.yml`, `helm/desplegar-manual.sh`, `helm/cv-server-chart/values.schema.json`, `values.gke.yaml`

## Context

On 19 Nov 2026 the GKE release had five revisions in 15 hours, all from a laptop:

- A `helm upgrade` from a branch without the PR #10 chart changes nearly deployed a pod that
  read placeholder secrets.
- Revision 5 runs `:814a90b`, an image built from `fix/sse-user-from-token`, a branch that is
  not pushed or merged. What runs on GKE is therefore code that exists in no shared history.
- CI pushed both `:<sha>` and `:latest`, used `--set` flags instead of a values file, and
  never deployed: both runs failed because `gke-gcloud-auth-plugin` was missing.

## Decision

1. **CI is the regular path.** `deploy.yml` runs only after a successful `tests` run for a push
   to `main` and deploys that run's `head_sha`.
2. **Images are named by commit.** Full 40-char SHA only. `values.schema.json` rejects any other
   tag at render time, and Artifact Registry `immutable_tags` (Terraform) stops a tag from being
   moved. An image is built and scanned once and then reused.
3. **One values file.** `values.gke.yaml`, from the same commit as the chart. No `--set` other
   than `image.tag`, and no `--reuse-values`.
4. **Automatic rollback.** `helm upgrade --atomic --timeout 5m`, then `helm test`.
5. **A guarded emergency path.** `helm/desplegar-manual.sh` refuses unless the checkout is
   `main`, clean, equal to `origin/main`, on the right kube context, and the image for that SHA
   already exists. It shows `helm diff` and asks for the short SHA to be typed.

## Consequences

- To get the SSE fix onto GKE through this path, `fix/sse-user-from-token` must be merged
  first. Otherwise the first CI deploy from `main` replaces `:814a90b` with code that lacks it.
- A hotfix takes as long as the test suite, about 11 minutes. That is accepted: it is the price
  of never deploying untested code.
- `helm rollback` stays available for incidents. After a rollback, `main` and the cluster
  differ until the fix is merged. The runbook says so.

## Alternatives considered

- **Argo CD / Flux (GitOps).** It would add pull-based reconciliation and drift correction. It
  also adds a controller (memory on nodes that were already full) and a second deploy system to
  learn. It is not worth it for one service. Revisit if there are several services or clusters.
- **Keep `latest` as a convenience tag.** Rejected: it makes "what is running?" unanswerable
  from the manifest.
