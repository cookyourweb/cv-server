#!/usr/bin/env bash
# Install or update the cluster add-ons with pinned chart versions.
#
#   infra/k8s/platform/instalar.sh diff  <component>   # default: show what would change
#   infra/k8s/platform/instalar.sh apply <component>   # asks for a typed confirmation
#
# component: ingress-nginx | cert-manager | external-secrets
#
# Needs the helm-diff plugin (docs/RUNBOOK-gke.md, prerequisites).
set -euo pipefail

MODO="${1:-diff}"
COMPONENTE="${2:?Usage: $0 diff|apply ingress-nginx|cert-manager|external-secrets}"
AQUI="$(cd "$(dirname "$0")" && pwd)"
CONTEXTO_ESPERADO="gke_cv-server-portfolio_europe-west1-b_cv-server-cluster"
# shellcheck source=versions.env
source "$AQUI/versions.env"

case "$COMPONENTE" in
  ingress-nginx)
    REPO=https://kubernetes.github.io/ingress-nginx; CHART=ingress-nginx
    NS=ingress-nginx; VERSION="$INGRESS_NGINX_CHART" ;;
  cert-manager)
    REPO=https://charts.jetstack.io; CHART=cert-manager
    NS=cert-manager; VERSION="$CERT_MANAGER_CHART" ;;
  external-secrets)
    REPO=https://charts.external-secrets.io; CHART=external-secrets
    NS=external-secrets; VERSION="$EXTERNAL_SECRETS_CHART" ;;
  *) echo "Unknown component: $COMPONENTE" >&2; exit 2 ;;
esac

contexto="$(kubectl config current-context)"
[[ "$contexto" == "$CONTEXTO_ESPERADO" ]] || {
  echo "kubectl points at '$contexto', not $CONTEXTO_ESPERADO. Refusing." >&2; exit 1; }
helm plugin list | grep -q '^diff' || { echo "Install helm-diff first." >&2; exit 1; }

ARGS=("$COMPONENTE" "$CHART" --repo "$REPO" --version "$VERSION"
      --namespace "$NS" -f "$AQUI/$COMPONENTE.values.yaml")

echo "== $COMPONENTE $VERSION in namespace $NS (diff against the live release)"
helm diff upgrade "${ARGS[@]}" --allow-unreleased --context 3

[[ "$MODO" == "apply" ]] || { echo "(diff only; run with 'apply' to change the cluster)"; exit 0; }

read -r -p "Apply this to $contexto? Type '$COMPONENTE' to confirm: " ok
[[ "$ok" == "$COMPONENTE" ]] || { echo "Cancelled."; exit 1; }
helm upgrade --install "${ARGS[@]}" --create-namespace --wait --atomic --timeout 5m
helm -n "$NS" status "$COMPONENTE" | head -8
