# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --legacy-peer-deps
COPY frontend/index.html frontend/tsconfig.json ./
COPY frontend/public ./public
COPY frontend/src ./src
RUN npm run build

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home qv && mkdir -p /var/lib/queryvault && chown 10001:10001 /var/lib/queryvault
COPY app.py agent.py db.py engine.py firewall.py paypal_client.py settings.py public_demo.py demo_quota.py public_agent.py interactive_api.py serve.py migrate_deployment.py initialize_interactive_quota.py migrations.sql migrations_synthetic.sql demo-evidence.json checkout_return.html ./
COPY --from=frontend /build/dist ./frontend/dist
USER 10001:10001
EXPOSE 8000
CMD ["python", "serve.py"]
