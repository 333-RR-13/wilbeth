# k8s/ — Kubernetes Manifests

Alle Dateien hier enthalten Platzhalter in spitzen Klammern `<LIKE_THIS>`.
Vor dem ersten `kubectl apply` müssen alle Platzhalter gefüllt werden.

## Platzhalter-Übersicht

| Platzhalter | Datei(en) | Bedeutung |
|---|---|---|
| `<NAMESPACE>` | alle | Kubernetes-Namespace, z. B. `tools-test` |
| `<DB_PASSWORD>` | `secret.example.yaml` | Passwort für den Postgres-User `wilbeth` |
| `<STORAGE_CLASS>` | `postgres.yaml` | StorageClass für das Postgres-PVC (beim Cluster-Admin erfragen) |
| `<HARBOR_REGISTRY>` | `deployment.yaml` | Hostname der Harbor-Registry, z. B. `harbor.example.com` |
| `<HARBOR_PROJECT>` | `deployment.yaml` | Harbor-Projektname, z. B. `wilbeth` oder `tools` |
| `<IMAGE_TAG>` | `deployment.yaml` | Image-Tag; wird von der Deploy-Pipeline auf `$(Build.BuildId)` gesetzt |
| `<INGRESS_HOST>` | `ingress.yaml` | Hostname der App, z. B. `wilbeth.tools.example.com` |
| `<INGRESS_CLASS>` | `ingress.yaml` | Name des Ingress-Controllers (`nginx`, `traefik`, …) |
| `<HARBOR_PULL_SECRET>` | `deployment.yaml` | Name des Image-Pull-Secrets; nur nötig wenn kein globales Cluster-Pull-Credential existiert |

## Image-Pull-Secret anlegen (optional)

Nur erforderlich wenn der Cluster kein globales Harbor-Pull-Credential besitzt:

```bash
kubectl create secret docker-registry harbor-pull \
  --docker-server=<HARBOR_REGISTRY> \
  --docker-username=... \
  --docker-password=... \
  -n <NAMESPACE>
```

Danach in `deployment.yaml` den Platzhalter `<HARBOR_PULL_SECRET>` durch `harbor-pull` ersetzen
(oder den gewählten Secret-Namen).  Wenn ein globales Pull-Credential vorhanden ist,
kann der `imagePullSecrets`-Block in `deployment.yaml` vollständig entfernt werden.

## Reihenfolge beim Erst-Deploy

1. **Secret anlegen** (niemals committen!):
   ```bash
   # secret.example.yaml kopieren, Platzhalter füllen, anwenden, dann lokal löschen
   cp k8s/secret.example.yaml k8s/secret.yaml
   # ... Werte eintragen ...
   kubectl apply -f k8s/secret.yaml -n <NAMESPACE>
   rm k8s/secret.yaml
   ```
2. **PostgreSQL deployen** (oder weglassen bei externer DB):
   ```bash
   kubectl apply -f k8s/postgres.yaml -n <NAMESPACE>
   ```
3. **App deployen** (nach erfolgreicher Build-Pipeline):
   ```bash
   kubectl apply -f k8s/deployment.yaml -f k8s/service.yaml -f k8s/ingress.yaml -n <NAMESPACE>
   # oder mit Kustomize:
   kubectl apply -k k8s/
   ```
4. **Seed einmalig ausführen** (nur beim ersten Mal):
   ```bash
   kubectl exec -n <NAMESPACE> deploy/wilbeth -- python -m seed.seed
   ```

## Sicherheitshinweis

`secret.example.yaml` ist nur eine Vorlage. Die Datei mit echten Credentials
darf **niemals** in Git committed werden. `.gitignore` enthält `k8s/secret.yaml`
als Schutz — prüfen, ob die Unternehmens-Git-Policy zusätzlich Pre-Commit-Hooks
oder eine Vault-Integration erfordert.
