#!/usr/bin/env bash
# EMERGENCY ONLY. Normal deploys are CI: push to main -> tests -> deploy.yml.
#
# Deploys exactly what CI would deploy, from a laptop, when CI is unavailable:
#   helm/desplegar-manual.sh --dry-run   # checks + helm diff, changes nothing
#   helm/desplegar-manual.sh             # checks + helm diff + typed confirmation
#
# Refuses unless ALL of these hold:
#   - the checkout is on `main`, with no uncommitted or untracked changes;
#   - HEAD is exactly origin/main (nothing unpushed, nothing missing);
#   - kubectl points at the cv-server cluster;
#   - the image for HEAD's full SHA already exists in Artifact Registry, i.e. CI
#     built and scanned it. This script never builds images.
# Then it uses the same chart, the same values.gke.yaml and the same flags as CI.
set -euo pipefail

RELEASE="cv-server"
NAMESPACE="default"
CONTEXTO_ESPERADO="gke_cv-server-portfolio_europe-west1-b_cv-server-cluster"
IMAGEN="europe-west1-docker.pkg.dev/cv-server-portfolio/cv-server/cv-server"
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
CHART="$RAIZ/helm/cv-server-chart"
VALUES="$CHART/values.gke.yaml"

fallo() { echo "REFUSED: $*" >&2; exit 1; }

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

rama="$(git -C "$RAIZ" rev-parse --abbrev-ref HEAD)"
[[ "$rama" == "main" ]] || fallo "on branch '$rama'. Deploys come from main only."

[[ -z "$(git -C "$RAIZ" status --porcelain)" ]] ||
  fallo "uncommitted or untracked changes. What is deployed must be exactly a commit."

git -C "$RAIZ" fetch --quiet origin main
local_sha="$(git -C "$RAIZ" rev-parse HEAD)"
remoto_sha="$(git -C "$RAIZ" rev-parse origin/main)"
[[ "$local_sha" == "$remoto_sha" ]] ||
  fallo "HEAD $local_sha is not origin/main $remoto_sha. Pull or push first."
SHA="$local_sha"

contexto="$(kubectl config current-context)"
[[ "$contexto" == "$CONTEXTO_ESPERADO" ]] ||
  fallo "kubectl points at '$contexto', not $CONTEXTO_ESPERADO."

gcloud artifacts docker images describe "$IMAGEN:$SHA" --format='value(image_summary.digest)' >/dev/null 2>&1 ||
  fallo "$IMAGEN:$SHA is not in Artifact Registry. Only images built and scanned by CI are deployed."

helm plugin list | grep -q '^diff' || fallo "the helm-diff plugin is missing (docs/RUNBOOK-gke.md, prerequisites)."

ARGS=("$RELEASE" "$CHART" --namespace "$NAMESPACE" -f "$VALUES" --set "image.tag=$SHA")

echo "== Release $RELEASE <- $SHA (diff against the live release)"
helm diff upgrade "${ARGS[@]}" --context 3

if $DRY_RUN; then
  echo "(dry run: nothing changed)"
  exit 0
fi

read -r -p "Deploy $SHA to $contexto? Type the first 7 characters of the SHA: " ok
[[ "$ok" == "${SHA:0:7}" ]] || fallo "confirmation did not match. Nothing deployed."

# --atomic: if the rollout does not become Ready in time, Helm rolls back by itself.
helm upgrade --install "${ARGS[@]}" --atomic --wait --timeout 5m
helm test "$RELEASE" --namespace "$NAMESPACE" --logs
