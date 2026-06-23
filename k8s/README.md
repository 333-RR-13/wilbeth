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

## Konfigurierte Werte & offene Punkte

Stand: gefüllt passend zum `pipelinetest`-Branch (Build über Firmen-Template).

| Wert | Aktuell gesetzt auf | Status |
|---|---|---|
| Namespace | `wilbeth` | gesetzt (`azure-pipelines.yml` + beide `kustomization.yaml`) |
| Image-Pfad | `harbor.grenkeleasing.com/wilbeth` | gesetzt – muss zu `imageRepository` der Pipeline passen |
| K8s-Environment | `env-staging-wilbeth.ai-apps-staging01-wilbeth` | gesetzt (`azure-pipelines.yml`) |
| Build/Registry-Auth | Firmen-Build-Template `jobs/build-container-image.yml@templates` | keine eigene Service Connection nötig |
| Ingress-Host | `wilbeth.k8s-ai-apps-staging.grenke.com` | ⚠️ Konvention – bei AI-Platform bestätigen (Wildcard-DNS `*.k8s-ai-apps-staging.grenke.com` → Ingress?) |
| Responsible-Team (Cert) | `rroetschke@grenke.de` | 🟡 temporär – später auf Team-Mail ändern |

## Token-Ersetzung durch die Pipeline

`replacetokens@6` (tokenPattern `doublebraces`) ersetzt beim Deploy:

| Token | Quelle |
|---|---|
| `{{dbPassword}}` | Azure-DevOps **Pipeline-Variable / Variable Group** `dbPassword` (secret) – temporär `DBPassword1!`, **nie im Git** |
| `{{imageTag}}` | Pipeline-Variable `$(Build.BuildId)` |

**Noch zu erledigen:** `dbPassword` in ADO als Secret-Variable anlegen; Ingress-Host
+ Team-Mail bestätigen; cert-manager-Issuer `keyfactor-command-issuer`, StorageClass
`longhorn` und DNS bestätigen.

## Lokales Rendern (ohne Pipeline)

```bash
# Voraussetzung: kubectl + kustomize installiert, Platzhalter bereits ersetzt
cd k8s/overlays/test
kubectl kustomize . > rendered.yaml
```
