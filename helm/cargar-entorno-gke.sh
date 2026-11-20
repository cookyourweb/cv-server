#!/usr/bin/env bash
# FALLBACK / BOOTSTRAP ONLY. The normal path is Secret Manager + External
# Secrets (infra/secrets/subir-a-secret-manager.sh, ADR-014).
#
# Use this only when Secret Manager or the operator is unavailable. It writes
# the hand-made Secret `cv-env`; switch the release to it with the guarded
# deploy and `--set secrets.envFromSecret=cv-env` (docs/RUNBOOK-gke.md, "Fallback").
#
# Usage:  ./helm/cargar-entorno-gke.sh <path-to-file.env>
#
# - Validates the file (required names, CORS, duplicates) and strips the outer
#   quotes that `--from-env-file` would otherwise keep literally.
# - Creates or updates the Secret. It does NOT run `helm upgrade` any more:
#   `--reuse-values` from a laptop is how an out-of-date chart nearly shipped
#   placeholders on 19 Nov 2026. Deploys go through CI or helm/desplegar-manual.sh.
# Never prints values: only variable names.
set -euo pipefail

FICHERO="${1:?Usage: $0 <path-to-file.env>}"
SECRETO="cv-env"
NAMESPACE="default"
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"

[[ -f "$FICHERO" ]] || { echo "No such file: $FICHERO" >&2; exit 1; }

python3 -I "$RAIZ/infra/secrets/entorno.py" names "$FICHERO"

LIMPIO="$(mktemp)"
chmod 600 "$LIMPIO"
trap 'rm -f "$LIMPIO"' EXIT
python3 -I "$RAIZ/infra/secrets/entorno.py" envfile "$FICHERO" > "$LIMPIO"

kubectl -n "$NAMESPACE" create secret generic "$SECRETO" --from-env-file="$LIMPIO" \
  --dry-run=client -o yaml | kubectl -n "$NAMESPACE" apply -f - >/dev/null
echo "Secret $NAMESPACE/$SECRETO updated. Pods read it only if the release uses it:"
echo "  helm get values cv-server -n $NAMESPACE | grep envFromSecret"
