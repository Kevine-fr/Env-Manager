FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Outils système : git (commit/push du dépôt Infrastructure) + ssh (push par clé).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Dépendances (couche cache séparée)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code de l'application
COPY app ./app
COPY scripts ./scripts
COPY web ./web

# Dossier des données (JSON généré)
RUN mkdir -p /app/data

ENV DEPLOY_ROOT=/deploy \
    DATA_DIR=/app/data \
    WEB_DIR=/app/web \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
