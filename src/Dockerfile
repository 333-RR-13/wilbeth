# Base-Image ueber den Harbor-Docker-Hub-Proxy (Firmen-Konvention; der Build-Cluster
# erreicht Docker Hub i.d.R. nicht direkt). Fuer lokale Builds ohne Harbor-Zugang
# diese Zeile temporaer auf  python:3.13-slim  aendern.
FROM harbor.grenkeleasing.com/docker.io/python:3.13-slim

WORKDIR /app

# WICHTIG: Build-Context ist der Repo-Root (Kaniko klont das Repo nach /workspace,
# das Firmen-Template setzt keinen Context-Parameter). Daher sind ALLE COPY-Pfade
# relativ zum Repo-Root -> src/...  (lokal entsprechend via docker-compose context: ..)

# Abhängigkeiten separat cachen – Layer wird nur neu gebaut, wenn sich
# requirements.txt ändert.
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Anwendungsquellen kopieren
COPY src/app/ app/
COPY src/alembic/ alembic/
COPY src/seed/ seed/
COPY src/alembic.ini .

# Entrypoint-Skript kopieren, ausführbar machen und defensiv CR entfernen
# (LF-only wird vom POSIX sh erwartet).
COPY src/docker-entrypoint.sh .
RUN sed -i 's/\r$//' /app/docker-entrypoint.sh \
    && chmod +x /app/docker-entrypoint.sh

# Non-root-Benutzer anlegen (UID/GID 1654). Muss zum securityContext.runAsUser
# im k8s-Deployment passen.
RUN groupadd -g 1654 app \
    && useradd -u 1654 -g 1654 -m -s /usr/sbin/nologin app

# /data für SQLite (lokaler Dev-Fallback) anlegen und dem App-User zugänglich machen.
# In k8s zeigt DATABASE_URL per ConfigMap/Secret auf das Postgres-Deployment.
RUN mkdir -p /data && chown 1654:1654 /data

# Dev-Defaults; in k8s per ConfigMap/Secret überschrieben.
ENV DATABASE_URL=sqlite:////data/wilbeth.db
ENV PORT=8080

VOLUME ["/data"]

EXPOSE 8080

# Der Pod spricht schlichtes HTTP – TLS terminiert der nginx-Ingress.
# curl fehlt in slim-Images, daher python urllib.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:'+os.environ.get('PORT','8080')+'/health')"

# Ab hier läuft alles als UID 1654 (Non-root, keine Linux-Capabilities benötigt).
USER 1654

# Migrationen + Serverstart übernimmt das Entrypoint-Skript.
ENTRYPOINT ["./docker-entrypoint.sh"]
