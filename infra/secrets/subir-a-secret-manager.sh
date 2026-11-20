#!/usr/bin/env bash
# Upload a .env export as a NEW VERSION of the Secret Manager secret
# `cv-server-env` (one JSON object, one key per variable). External Secrets
# then syncs it into the Kubernetes Secret `cv-env-sm` (ADR-014).
#
# Usage:  infra/secrets/subir-a-secret-manager.sh <path-to-file.env>
#
# Never prints values: the payload goes straight from Python to gcloud through
# a pipe. Prints variable names and the new version number only.
set -euo pipefail

FICHERO="${1:?Usage: $0 <path-to-file.env>}"
PROYECTO="${PROYECTO:-cv-server-portfolio}"
SECRETO="${SECRETO:-cv-server-env}"
AQUI="$(cd "$(dirname "$0")" && pwd)"

[[ -f "$FICHERO" ]] || { echo "No such file: $FICHERO" >&2; exit 1; }

# Validates first (required names, CORS, quotes, duplicates). Names only.
python3 -I "$AQUI/entorno.py" names "$FICHERO"

read -r -p "Add these variables as a new version of $SECRETO in $PROYECTO? Type 'yes': " ok
[[ "$ok" == "yes" ]] || { echo "Cancelled."; exit 1; }

python3 -I "$AQUI/entorno.py" json "$FICHERO" |
  gcloud secrets versions add "$SECRETO" --project "$PROYECTO" --data-file=- \
    --format='value(name)' | sed 's#.*/versions/#New version: #'

echo "External Secrets picks it up within its refreshInterval (1h), or now with:"
echo "  kubectl -n default annotate externalsecret cv-server-env force-sync=\$(date +%s) --overwrite"
echo "Pods read env at start: then run  kubectl -n default rollout restart deployment/cv-server-cv-server"
