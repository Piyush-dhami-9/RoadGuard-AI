#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Fixed resource names live in .azure/deploy.env so reruns update the same
# resources instead of provisioning a new randomly named set each time.
if [[ -f .azure/deploy.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .azure/deploy.env
  set +a
fi

AZ="${AZ:-$REPO_ROOT/.azure/azcli-venv/bin/az}"
command -v "$AZ" >/dev/null 2>&1 || AZ=az

RESOURCE_GROUP="${RESOURCE_GROUP:-roadguard-rg-eastasia}"
LOCATION="${LOCATION:-eastasia}"
REGISTRY_NAME="${REGISTRY_NAME:?REGISTRY_NAME is required}"
POSTGRES_NAME="${POSTGRES_NAME:?POSTGRES_NAME is required}"
ENVIRONMENT_NAME="${ENVIRONMENT_NAME:-roadguard-env}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
POSTGRES_ADMIN_LOGIN="${POSTGRES_ADMIN_LOGIN:-roadguard}"

# Container Apps runs linux/amd64 only; this repo is built on arm64 Macs too.
BUILD_PLATFORM="${BUILD_PLATFORM:-linux/amd64}"

if [[ -z "${POSTGRES_ADMIN_PASSWORD:-}" && -f .azure/postgres-admin-password ]]; then
  POSTGRES_ADMIN_PASSWORD="$(cat .azure/postgres-admin-password)"
fi
if [[ -z "${POSTGRES_ADMIN_PASSWORD:-}" ]]; then
  read -r -s -p "PostgreSQL administrator password: " POSTGRES_ADMIN_PASSWORD
  echo
fi
: "${POSTGRES_ADMIN_PASSWORD:?A PostgreSQL administrator password is required}"

deploy_infra() {
  "$AZ" deployment group create \
    --resource-group "$RESOURCE_GROUP" \
    --name "roadguard-$1" \
    --template-file infra/main.bicep \
    --parameters \
      location="$LOCATION" \
      environmentName="$ENVIRONMENT_NAME" \
      registryName="$REGISTRY_NAME" \
      postgresName="$POSTGRES_NAME" \
      backendImage="$2" \
      frontendImage="$3" \
      postgresAdminLogin="$POSTGRES_ADMIN_LOGIN" \
      postgresAdminPassword="$POSTGRES_ADMIN_PASSWORD" \
    --output none
}

"$AZ" group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none
if ! "$AZ" acr show --resource-group "$RESOURCE_GROUP" --name "$REGISTRY_NAME" >/dev/null 2>&1; then
  "$AZ" acr create --resource-group "$RESOURCE_GROUP" --name "$REGISTRY_NAME" \
    --sku Basic --admin-enabled true --output none
fi

REGISTRY_LOGIN_SERVER="$("$AZ" acr show --name "$REGISTRY_NAME" --resource-group "$RESOURCE_GROUP" --query loginServer -o tsv)"
"$AZ" acr login --name "$REGISTRY_NAME" >/dev/null

BACKEND_IMAGE="$REGISTRY_LOGIN_SERVER/roadguard-backend:$IMAGE_TAG"
FRONTEND_IMAGE="$REGISTRY_LOGIN_SERVER/roadguard-frontend:$IMAGE_TAG"

# Pass 1: backend only. The frontend needs the backend's public URL baked in at
# build time, so it cannot be built until the backend app exists.
docker build --build-arg INSTALL_MODEL_DEPS=false --platform "$BUILD_PLATFORM" -f backend/Dockerfile -t "$BACKEND_IMAGE" .
docker push "$BACKEND_IMAGE"
deploy_infra backend "$BACKEND_IMAGE" ''

BACKEND_FQDN="$("$AZ" containerapp show --name roadguard-backend --resource-group "$RESOURCE_GROUP" --query properties.configuration.ingress.fqdn -o tsv)"
BACKEND_URL="https://$BACKEND_FQDN"

# Pass 2: frontend, built against the live backend URL, then a full deployment.
docker build --platform "$BUILD_PLATFORM" -f frontend/Dockerfile \
  --build-arg VITE_API_URL="$BACKEND_URL" -t "$FRONTEND_IMAGE" frontend
docker push "$FRONTEND_IMAGE"
deploy_infra full "$BACKEND_IMAGE" "$FRONTEND_IMAGE"

FRONTEND_FQDN="$("$AZ" containerapp show --name roadguard-frontend --resource-group "$RESOURCE_GROUP" --query properties.configuration.ingress.fqdn -o tsv)"

echo "Backend:  $BACKEND_URL"
echo "Frontend: https://$FRONTEND_FQDN"
