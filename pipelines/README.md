# pipelines/ — Azure DevOps YAML Pipelines

## Übersicht

| Datei | Zweck |
|---|---|
| `azure-pipelines-build.yml` | Test (pytest) + Docker Build & Push zu Harbor |
| `azure-pipelines-deploy.yml` | Kubernetes-Deployment aus dem frisch gebauten Image |

## Platzhalter — vor erster Ausführung füllen

| Platzhalter | Wo | Bedeutung |
|---|---|---|
| `<GITHUB_SERVICE_CONNECTION>` | build | Name der Azure DevOps Service Connection für den GitHub-Repo-Zugriff |
| `<HARBOR_SERVICE_CONNECTION>` | build | Name der Azure DevOps Service Connection zur Harbor-Registry |
| `<HARBOR_REGISTRY>` | build + deploy | Hostname der Harbor-Registry, z. B. `harbor.example.com` |
| `<HARBOR_PROJECT>` | build + deploy | Harbor-Projektname, z. B. `wilbeth` |
| `<K8S_SERVICE_CONNECTION>` | deploy | Name der Azure DevOps Service Connection zum Kubernetes-Cluster |
| `<NAMESPACE>` | deploy | Kubernetes-Namespace, z. B. `tools-test` |
| `<BUILD_PIPELINE_ID>` | deploy | Name oder ID der Build-Pipeline in Azure DevOps (für Pipeline-Resource-Trigger) |

## Service Connections anlegen

In Azure DevOps unter **Project Settings → Service Connections**:

1. **GitHub**: Typ „GitHub", OAuth oder PAT, Zugriff auf `333-RR-13/wilbeth`.
2. **Harbor**: Typ „Docker Registry", Registry-URL = `https://<HARBOR_REGISTRY>`,
   Credentials = Harbor-Serviceaccount mit Push-Rechten auf `<HARBOR_PROJECT>`.
3. **Kubernetes**: Typ „Kubernetes", Kubeconfig oder Service-Account-Token für den
   Namespace `<NAMESPACE>` auf dem `tools-test`-Cluster.

## Ablauf (zusammengefasst)

```
GitHub Push (main)
  └─► Build-Pipeline
        ├─ Stage: Test      — pytest -q (CI-Gate; kein Image ohne grüne Tests)
        └─ Stage: Build     — docker buildAndPush → Harbor (Tags: BuildId + latest)
              └─► (Trigger) Deploy-Pipeline
                    └─ Stage: Deploy  — kubectl apply → tools-test Namespace
```
