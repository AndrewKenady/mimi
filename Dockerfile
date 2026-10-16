# syntax=docker/dockerfile:1.7
# hadolint global ignore=DL3006
# (DL3006: the base images are pinned by tag and digest through the ARGs below.)
#
# Mimi in a container: Core + UI + engines in the image (~2 GB, ~500 MB to download), content in the /data volume.
#
#   docker compose up -d                      then open http://localhost:7600
#   docker compose run --rm mimi content add lite --region uk
#
# Targets: `cpu` (default, any x86-64 or arm64 machine) and `vulkan` (adds Mesa's Vulkan
# drivers for AMD/Intel GPUs passed in with /dev/dri). See docs/INSTALL.md#docker.
#
# Behind a TLS-intercepting proxy, pass its CA as a build secret:
#   docker build --secret id=ca,src=/path/to/ca.pem .

ARG PYTHON_IMAGE=python:3.12.15-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ARG NODE_IMAGE=node:22.23.3-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392

# --------------------------------------------------------------------------- the app UI
FROM ${NODE_IMAGE} AS ui
WORKDIR /src/ui
COPY ui/package.json ui/package-lock.json ./
RUN --mount=type=secret,id=ca,required=false \
    if [ -s /run/secrets/ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca; fi; \
    npm ci --no-audit --no-fund
COPY ui/ ./
RUN npm run build

# --------------------------------------------------------------------------- engines
# llama.cpp, kiwix-serve and pmtiles for the image's architecture, pinned and sha256-checked
# by the same code as the native installers.
FROM ${PYTHON_IMAGE} AS engines
WORKDIR /opt/mimi
COPY scripts/fetch.py scripts/
COPY manifests/runtimes.json manifests/
RUN --mount=type=secret,id=ca,required=false \
    if [ -s /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
    MIMI_CONTENT=/tmp/content python scripts/fetch.py --only runtimes \
    && rm -rf /tmp/content

# --------------------------------------------------------------------------- Python packages
FROM ${PYTHON_IMAGE} AS python
COPY core/pyproject.toml /tmp/pyproject.toml
RUN --mount=type=secret,id=ca,required=false \
    if [ -s /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    python -c "import tomllib; print('\n'.join(tomllib.load(open('/tmp/pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check -r /tmp/requirements.txt "pyvalhalla>=3.9,<4" "osmium>=4,<5"

# --------------------------------------------------------------------------- runtime (CPU)
FROM ${PYTHON_IMAGE} AS cpu
# libgomp1: OpenMP for llama.cpp's CPU backend. tini: reaps zombies and forwards signals,
# so `docker stop` shuts Core down cleanly and Core stops its engines. Debian packages follow
# the pinned base image's security updates rather than exact versions.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 tini aria2 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin mimi \
    && mkdir -p /data && chown mimi:mimi /data
COPY --from=python /opt/venv /opt/venv
WORKDIR /opt/mimi
COPY LICENSE ./
COPY config/ config/
COPY manifests/ manifests/
COPY scripts/ scripts/
COPY tools/ tools/
COPY core/mimi/ core/mimi/
COPY core/pyproject.toml core/
COPY --from=engines /opt/mimi/bin/ bin/
COPY --from=ui /src/ui/build/ ui/build/
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/opt/mimi/core \
    PYTHONUNBUFFERED=1 \
    MIMI_HOME=/opt/mimi \
    MIMI_CONTENT=/data \
    MIMI_DATA=/data/user \
    MIMI_LOGS=/data/logs \
    MIMI_HOST=0.0.0.0
# Owner sign-in: inside a container no browser is ever on loopback; see MIMI_LOCAL_PEERS in
# docker-compose.yml and docs/INSTALL.md#docker before publishing port 7600 beyond 127.0.0.1.
USER mimi
VOLUME ["/data"]
EXPOSE 7600
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7600/api/health', timeout=4)"]
ENTRYPOINT ["tini", "--", "/opt/mimi/scripts/docker-entrypoint.sh"]
CMD ["serve"]

# --------------------------------------------------------------------------- runtime (Vulkan GPU)
FROM cpu AS vulkan
USER root
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends libvulkan1 mesa-vulkan-drivers \
    && rm -rf /var/lib/apt/lists/*
USER mimi
