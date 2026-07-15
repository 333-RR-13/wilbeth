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

## Auth (Entra OIDC)

Wilbeth authentifiziert sich per OIDC gegen Entra ID. Der `wilbeth`-Container liest dazu u. a.
`AUTH_MODE`, `OIDC_CLIENT_ID`, `OIDC_DISCOVERY_URL`, `OIDC_REDIRECT_URI`, die drei
`OIDC_GROUP_*`-Variablen (Klartext, nicht geheim – gesetzt in `deployment.wilbeth.yaml`) sowie
`OIDC_CLIENT_SECRET` und `SESSION_SECRET` (geheim – via `secretKeyRef` aus `wilbeth-secrets`).

**Benötigte zusätzliche ADO-Pipeline-Variablen** (analog zu `dbPassword`, **als „secret“ markieren**):

| Variable | Zweck |
|---|---|
| `oidcClientSecret` | Client-Secret der Entra-App-Registrierung → Token `{{oidcClientSecret}}` in `secret.yaml` |
| `sessionSecret` | Secret zum Signieren der Session-Cookies → Token `{{sessionSecret}}` in `secret.yaml` |

⚠️ **Ohne diese beiden Pipeline-Variablen scheitert der Deploy am `replacetokens`-Schritt**
(`missingVarLog: error` → unaufgelöste `{{oidcClientSecret}}` / `{{sessionSecret}}`-Tokens).

Redirect-URI (muss in der Entra-App-Registrierung als Reply-URL hinterlegt sein):
`https://wilbeth.k8s-ai-apps-staging.grenke.com/auth/callback`

Das Client-Secret darf **niemals im Klartext ins Repo** – es existiert nur als ADO-Pipeline-Secret
und wird zur Deploy-Zeit per Token-Ersetzung in `wilbeth-secrets` (Kubernetes Secret) eingesetzt.

## Lokales Rendern (ohne Pipeline)

```bash
# Voraussetzung: kubectl + kustomize installiert, Platzhalter bereits ersetzt
cd k8s/overlays/test
kubectl kustomize . > rendered.yaml
```
