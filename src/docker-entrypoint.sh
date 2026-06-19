#!/bin/sh
# docker-entrypoint.sh fuer Wilbeth (laeuft als non-root, UID 1654).
#
# TLS uebernimmt der nginx-Ingress -> der Pod spricht schlichtes HTTP.
#
# HINWEIS MIGRATION:
# alembic upgrade head laeuft bei jedem Container-Start VOR dem Server.
# Das setzt replicaCount=1 voraus! Bei replicaCount>1 wuerden mehrere
# Pods gleichzeitig migrieren -> Race Condition auf das Schema.
# TODO: Migration spaeter in einen Init-Container / Job auslagern.

set -e

PORT=${PORT:-8080}

echo "[entrypoint] Fuehre alembic upgrade head aus..."
alembic upgrade head
echo "[entrypoint] Migrationen abgeschlossen. Starte uvicorn auf Port $PORT (HTTP)."

exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 1
