# PyRest AKS Deployment Guide

Deploy PyRest to Azure Kubernetes Service (AKS) with per-app scaling and scale-to-zero for cost optimization.

## Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │              AKS Cluster                     │
                    │                                              │
  Internet/VPN ──▶  │  Nginx Ingress Controller                    │
                    │     │                                        │
                    │     ├── /pyrest/*          → pyrest-main     │
                    │     ├── /pyrest/tm1data/*  → pyrest-tm1data  │
                    │     ├── /pyrest/pov/*      → pyrest-pov      │
                    │     └── /pyrest/tm1query/* → pyrest-tm1query │
                    │                                              │
                    │  KEDA HTTP Add-on                            │
                    │     Scales isolated apps 0↔2 based on HTTP   │
                    │     traffic. Idle apps = 0 replicas = $0.    │
                    └─────────────────────────────────────────────┘
```

**Key points:**
- The main framework (`pyrest-main`) always runs 1 replica
- Each isolated app is a separate Deployment, scaled by KEDA
- Apps with no traffic scale to 0 pods (zero compute cost)
- Cold start when a request arrives: ~3-5 seconds
- No Nginx container needed -- AKS Ingress Controller handles routing

## Prerequisites

1. **AKS Cluster** with:
   - Nginx Ingress Controller (`ingress-nginx`)
   - KEDA add-on enabled
   - KEDA HTTP Add-on installed

2. **Azure Container Registry (ACR)** linked to the AKS cluster

3. **Tools:**
   - `az` CLI (authenticated)
   - `kubectl` (configured for your AKS cluster)
   - `docker` (for building images)

## Step 1: Enable KEDA on AKS

```bash
# Enable the KEDA add-on on your AKS cluster
az aks update \
  --resource-group <RESOURCE_GROUP> \
  --name <CLUSTER_NAME> \
  --enable-keda

# Install KEDA HTTP Add-on
# See: https://github.com/kedacore/http-add-on
helm install http-add-on kedacore/keda-add-ons-http \
  --namespace keda \
  --create-namespace
```

## Step 2: Install Nginx Ingress Controller

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update

helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.service.annotations."service\.beta\.kubernetes\.io/azure-load-balancer-health-probe-request-path"=/healthz
```

## Step 3: Build and Push Images

```bash
# Login to ACR
az acr login --name <ACR_NAME>

# Set registry
export REGISTRY=<ACR_NAME>.azurecr.io

# Build and push all images (main + all isolated apps)
./scripts/build-all-images.sh $REGISTRY latest --push

# Or build a single app
./scripts/build-app-image.sh tm1data $REGISTRY latest
docker push $REGISTRY/pyrest-tm1data:latest
```

### Air-gapped environments

```bash
export PIP_INDEX_URL=https://pypi.internal.company.com/simple/
export PIP_TRUSTED_HOST=pypi.internal.company.com

./scripts/build-all-images.sh $REGISTRY latest --push
```

## Step 4: Create Namespace and Config

```bash
# Create namespace
kubectl apply -f k8s/base/namespace.yaml

# Create ConfigMap (edit config.json values as needed)
kubectl apply -f k8s/base/configmap.yaml

# Create auth secret (replace with your actual auth_config.json)
kubectl create secret generic pyrest-auth-config \
  --namespace pyrest \
  --from-file=auth_config.json=./auth_config.json
```

## Step 5: Deploy

```bash
# Update image references in manifests first:
#   Replace ${ACR_REGISTRY} with your actual registry
#   Replace myregistry.azurecr.io with your actual registry

# Deploy main framework
kubectl apply -f k8s/base/main-deployment.yaml
kubectl apply -f k8s/base/main-service.yaml

# Deploy isolated apps (each includes Deployment + Service + KEDA ScaledObject)
kubectl apply -f k8s/apps/tm1data.yaml
kubectl apply -f k8s/apps/pov.yaml

# Deploy ingress rules
kubectl apply -f k8s/base/ingress.yaml
```

## Step 6: Verify

```bash
# Check all pods
kubectl get pods -n pyrest

# Main framework should be Running, isolated apps should show 0/0 (scaled to zero)
# NAME                             READY   STATUS    RESTARTS
# pyrest-main-xxx                  1/1     Running   0
# (tm1data and pov have 0 pods -- they'll start on first request)

# Check KEDA scaled objects
kubectl get httpscaledobjects -n pyrest

# Check services
kubectl get svc -n pyrest

# Check ingress
kubectl get ingress -n pyrest

# Test health
curl http://<INGRESS_IP>/pyrest/health
```

## Adding a New Isolated App

1. Create the app in `apps/<app_name>/` with `handlers.py`, `config.json`, `requirements.txt`

2. Build and push the image:
   ```bash
   ./scripts/build-app-image.sh <app_name> $REGISTRY latest
   docker push $REGISTRY/pyrest-<app_name>:latest
   ```

3. Copy and customize the manifest template:
   ```bash
   cp k8s/apps/template-deployment.yaml k8s/apps/<app_name>.yaml
   # Replace all ${APP_NAME} with actual app name
   # Replace ${ACR_REGISTRY} with actual registry
   # Adjust resource limits as needed
   ```

4. Add an ingress path rule in `k8s/base/ingress.yaml`:
   ```yaml
   - path: /pyrest/<app_name>(/.*)?$
     pathType: ImplementationSpecific
     backend:
       service:
         name: pyrest-<app_name>
         port:
           number: 8001
   ```

5. Deploy:
   ```bash
   kubectl apply -f k8s/apps/<app_name>.yaml
   kubectl apply -f k8s/base/ingress.yaml
   ```

## Scaling Configuration

Each app's KEDA `HTTPScaledObject` controls its scaling behavior:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `replicas.min` | 0 | Minimum replicas (0 = scale-to-zero) |
| `replicas.max` | 2 | Maximum replicas under load |
| `cooldownPeriod` | 300 | Seconds of no traffic before scaling to min |
| `scalingMetric.requestRate.targetValue` | 10 | Requests/sec per replica before scaling up |

**Example: Keep an app always warm (no scale-to-zero):**
```yaml
replicas:
  min: 1  # Always at least 1 replica
  max: 4
cooldownPeriod: 600
```

**Example: Aggressive scaling for heavy workloads:**
```yaml
replicas:
  min: 0
  max: 8
scalingMetric:
  requestRate:
    targetValue: 5  # Scale up sooner
cooldownPeriod: 120  # Scale down faster
```

## Dual-Mode: Local Dev vs AKS

| | Local (docker-compose) | AKS (k8s manifests) |
|---|---|---|
| Container model | Single container, all apps | Per-app containers |
| Routing | In-container Nginx | Ingress Controller |
| Scaling | None (fixed) | KEDA scale-to-zero |
| App code changes | None | None |
| Use case | Development | Production |

The same `handlers.py`, `config.json`, and `requirements.txt` work in both modes. No app code changes needed.

## Troubleshooting

**App not scaling up from zero:**
```bash
# Check KEDA HTTP Add-on logs
kubectl logs -n keda -l app=keda-add-ons-http-interceptor

# Check KEDA operator logs
kubectl logs -n keda -l app=keda-operator
```

**App health check failing:**
```bash
# Check pod logs
kubectl logs -n pyrest -l app=pyrest-<app_name>

# Exec into pod to test health manually
kubectl exec -it -n pyrest deploy/pyrest-<app_name> -- \
  wget -qO- http://localhost:8001/pyrest/<app_name>/health
```

**Image pull errors:**
```bash
# Verify ACR is linked to AKS
az aks check-acr --resource-group <RG> --name <CLUSTER> --acr <ACR_NAME>.azurecr.io
```
