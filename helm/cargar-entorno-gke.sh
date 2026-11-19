#!/usr/bin/env bash
# Loads the real production config (the one on Render) into GKE.
#
# Usage:  ./helm/cargar-entorno-gke.sh <path-to-file.env>
#
# - Creates or updates the "cv-env" Secret with EVERY variable in the file.
# - Runs helm upgrade so the pod reads them with envFrom.
# - Waits for the rollout and checks the API now has authentication.
# Never prints values: only variable names.
set -euo pipefail

FICHERO="${1:?Uso: $0 <ruta-al-fichero.env>}"
SECRETO="cv-env"
RELEASE="cv-server"
CHART="$(dirname "$0")/cv-server-chart"
URL="https://api.cookyourwebai.es"

[[ -f "$FICHERO" ]] || { echo "No existe $FICHERO"; exit 1; }

obligatorias=(DATABASE_URL CLAUDE_API_KEY GROQ_API_KEY NOTION_TOKEN CLAVE_MAQUINA
              OIDC_AUDIENCIA OIDC_EMISORES CORS_ORIGENES)
faltan=()
for v in "${obligatorias[@]}"; do
  grep -qE "^${v}=.+" "$FICHERO" || faltan+=("$v")
done
if ((${#faltan[@]})); then
  echo "Faltan (o están vacías): ${faltan[*]}"; exit 1
fi

if ! grep -E '^CORS_ORIGENES=' "$FICHERO" | grep -q 'empleo.cookyourwebai.es'; then
  echo "CORS_ORIGENES no incluye https://empleo.cookyourwebai.es: el panel no podría llamar a GKE."
  exit 1
fi

echo "Variables que se cargan: $(grep -cE '^[A-Z_]+=' "$FICHERO")"

kubectl create secret generic "$SECRETO" --from-env-file="$FICHERO" \
  --dry-run=client -o yaml | kubectl apply -f -

helm upgrade "$RELEASE" "$CHART" --reuse-values --set secrets.envFromSecret="$SECRETO"
kubectl rollout restart deployment "${RELEASE}-cv-server"
kubectl rollout status deployment "${RELEASE}-cv-server" --timeout=180s

echo "--- comprobación"
curl -s -o /dev/null -w "/health -> %{http_code}\n" "$URL/health"
curl -s "$URL/clave-api?proveedor=anthropic"; echo
