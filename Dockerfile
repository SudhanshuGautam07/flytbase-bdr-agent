FROM node:20-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    N8N_VERSION=2.8.4

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g "n8n@${N8N_VERSION}" --no-audit --no-fund

WORKDIR /app
COPY . /app

RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir fastapi uvicorn \
    && chmod +x /app/render-entrypoint.sh

ENV PATH="/opt/venv/bin:${PATH}"
EXPOSE 10000

CMD ["/app/render-entrypoint.sh"]
