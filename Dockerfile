FROM node:20-bookworm-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates libatomic1 libglib2.0-0 libgomp1 libgl1 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-traffix.txt ./
RUN --mount=type=cache,target=/root/.cache/pip PIP_NO_CACHE_DIR=0 pip install -r requirements-traffix.txt

COPY . ./
COPY --from=frontend-build /frontend/dist ./frontend/dist
RUN groupadd --gid 1000 traffix \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin traffix \
    && mkdir -p data/generated/live \
    && chown -R 1000:1000 /app

USER 1000:1000
EXPOSE 7860
ENTRYPOINT ["sh", "deploy/live-entrypoint.sh"]
