# Deployment guide

## Live deployment

The app is deployed to Azure Container Apps in East Asia:

- Website: https://roadguard-frontend.ashypebble-8c6b3da9.eastasia.azurecontainerapps.io
- API: https://roadguard-backend.ashypebble-8c6b3da9.eastasia.azurecontainerapps.io
- API docs: https://roadguard-backend.ashypebble-8c6b3da9.eastasia.azurecontainerapps.io/docs

Redeploy with `./scripts/deploy-azure.sh`. Resource names are pinned in
`.azure/deploy.env` so a rerun updates the same resources. See
`.azure/summary.copilotmd` for the full inventory and follow-ups.

### Build requirements

- Images must be built for `linux/amd64`; Container Apps does not run arm64
  images, which is what an Apple Silicon host builds by default.
- Build locally and push. ACR Tasks (`az acr build`) is blocked on this
  subscription, so the registry cannot build images for you.
- The backend image needs several GB of free disk while building.


This project is set up for a containerized deployment pattern that matches a typical Azure hosting setup:

- Frontend static app served by Nginx
- Backend FastAPI API served by Uvicorn
- PostgreSQL database for inspection records
- Optional YOLO model weights mounted at `model/weights/best.pt`

## Recommended target

Use Azure Container Apps for the app tier and Azure Database for PostgreSQL Flexible Server for the database.

This matches the existing architecture:

- `frontend` -> static web app
- `backend` -> API service
- `db` -> persistent relational data store
- `model` -> optional ML artifact mount

## Local production-style run

```bash
docker compose -f docker-compose.prod.yml up --build
```

The frontend is served on:

- http://localhost:5173

The API is served on:

- http://localhost:8000/docs

## Azure deployment flow

1. Create a resource group.
2. Create an Azure Container Registry.
3. Build and push the backend and frontend images.
4. Create a PostgreSQL Flexible Server.
5. Deploy both services to Azure Container Apps.
6. Set environment variables for:
   - `DATABASE_URL`
   - `CORS_ORIGINS`
   - `VITE_API_URL`
   - `MODEL_WEIGHTS`
7. Configure ingress and secret references.

### Azure CLI example

```bash
az group create --name roadguard-rg --location eastus
az acr create --resource-group roadguard-rg --name roadguardacr123 --sku Basic
az postgres flexible-server create \
  --resource-group roadguard-rg \
  --name roadguard-db \
  --location eastus \
  --admin-user roadguard \
  --admin-password '<StrongPassword>' \
  --sku-name Standard_B1ms \
  --version 16
```

Then build and push the app images with Docker, then create Container Apps for each service using the registry images.

## Environment variables

Set these in production:

```env
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/roadguard
CORS_ORIGINS=https://<frontend-domain>
VITE_API_URL=https://<backend-domain>
MODEL_WEIGHTS=/app/model/weights/best.pt
```

## Notes

- The app already contains a demo fallback for inference when no model weights are present.
- The YOLO weights are required for production-grade detection quality.
- The app will run without the trained model, but accuracy will be limited to the OpenCV demo detector.

