FROM python:3.13-slim

WORKDIR /app

# Install dependencies first – cached layer unless requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application sources
COPY app/ app/
COPY alembic/ alembic/
COPY seed/ seed/
COPY alembic.ini .

# SQLite data lives on a volume so it survives container restarts
ENV DATABASE_URL=sqlite:////data/wilbeth.db
RUN mkdir /data
VOLUME ["/data"]

EXPOSE 8000

# Healthcheck uses python urllib – curl is absent in slim images
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Run migrations then start the server.
# Using sh -c avoids a separate shell script (no CRLF risk on Windows dev machines).
# --workers 1: alembic upgrade head runs on every container start; multiple workers would
# race to apply migrations simultaneously and corrupt the schema. Keep at 1.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
