# k8s – Wilbeth Kubernetes-Deployment

Kustomize-basierte Struktur für das Wilbeth-Deployment im grenke-Cluster.

## Struktur

```
k8s/
├── base/                         # Gemeinsame Manifeste (alle Environments)
│   ├── kustomization.yaml
│   ├── configmap.yaml            # Nicht-sensitive Konfiguration (POSTGRES_USER, PORT …)
│   ├── secret.yaml               # Sensible Werte – Tokens werden von der Pipeline ersetzt
│   ├── pvc.yaml                  # Postgres-PersistentVolumeClaim (longhorn, 10 Gi)
│   ├── deployment.postgres.yaml  # PostgreSQL 16 (non-root UID 999)
│   ├── deployment.wilbeth.yaml   # Wilbeth FastAPI App (non-root UID 1654)
│   ├── service.wilbeth.yaml      # ClusterIP :8080
│   └── service.postgres.yaml     # ClusterIP :5432
└── overlays/
    └── test/                     # Test-Environment
        ├── kustomization.yaml
        └── ingress.yaml          # Ingress + cert-manager Certificate
```

## Platzhalter – wen fragen?

Alle folgenden Werte sind **unbekannt** und müssen vor dem ersten Deployment
von der **AI-Platform** (bzw. dem zuständigen Ops-Team) erfragt werden.

| Platzhalter | Wo verwendet | Wen fragen |
|---|---|---|
| `<<<HARBOR_PROJEKT>>>` | `deployment.wilbeth.yaml`, `azure-pipelines.yml` | AI-Platform – Harbor-Projektname (z. B. `ai-apps`) |
| `<<<NAMESPACE>>>` | `base/kustomization.yaml`, `overlays/test/kustomization.yaml`, `azure-pipelines.yml` | AI-Platform – k8s-Namespace (z. B. `wilbeth-test`) |
| `<<<K8S_ENVIRONMENT>>>` | `azure-pipelines.yml` | AI-Platform – Azure DevOps Environment-Name (Muster wie `env-test-wilbeth.cluster-wilbeth-test`) |
| `<<<HARBOR_SERVICE_CONNECTION>>>` | `azure-pipelines.yml` | AI-Platform – Name der Harbor Docker Registry Service Connection in Azure DevOps |
| `<<<HOST>>>` | `overlays/test/ingress.yaml` | AI-Platform – Ingress-Hostname (z. B. `wilbeth.k8s-ai-apps-test.grenke.com`) |
| `<<<RESPONSIBLE_TEAM_EMAIL>>>` | `overlays/test/ingress.yaml` | AI-Platform – Team-E-Mail-Adresse für Keyfactor-Annotation (z. B. `T-G-DE-IT-OPS-DP@GRENKE.DE`) |

## Token-Ersetzung durch die Pipeline

Die Azure-DevOps-Pipeline (replacetokens@6, tokenPattern `doublebraces`) ersetzt
zur Laufzeit folgende Tokens in den Manifesten:

| Token | Quelle |
|---|---|
| `{{dbPassword}}` | Pipeline Variable / Variable Group – `dbPassword` (secret) |
| `{{imageTag}}` | Pipeline Variable – `$(Build.BuildId)` |

**Variable Group**: Name und Ablageort (Azure Key Vault oder manuell) ebenfalls
bei der AI-Platform erfragen.

## Lokales Rendern (ohne Pipeline)

```bash
# Voraussetzung: kubectl + kustomize installiert, Platzhalter bereits ersetzt
cd k8s/overlays/test
kubectl kustomize . > rendered.yaml
```
