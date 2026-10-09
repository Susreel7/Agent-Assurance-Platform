# Multi-stage build. One image serves api, worker and migrate — they differ only by
# command. Cloud SDKs are optional extras so a BYOC image for one cloud does not carry
# the other two.
#
# Build the cloud-specific variants with:
#   docker build --build-arg EXTRAS=aws  -t aap-api:x.y.z-aws  .
#   docker build --build-arg EXTRAS=azure -t aap-api:x.y.z-azure .
#   docker build --build-arg EXTRAS=gcp  -t aap-api:x.y.z-gcp  .
#   docker build --build-arg EXTRAS=none -t aap-api:x.y.z-airgap .

ARG PYTHON_VERSION=3.12

# ------------------------------------------------------------------ builder
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# Build dependencies for psycopg and WeasyPrint. Kept out of the runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml ./

ARG EXTRAS=dev

# Two installs, on purpose.
#
# The first resolves dependencies from pyproject.toml alone, so editing source does not
# reinstall the whole dependency set on every build. setuptools declares
# `packages = ["app", "seed"]` explicitly and refuses to build metadata if those
# directories are missing, so they are stubbed here — the real ones arrive below and
# the second install replaces the stub.
RUN mkdir -p app seed \
    && touch app/__init__.py seed/__init__.py \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && if [ "$EXTRAS" = "none" ]; then \
           /opt/venv/bin/pip install .; \
       else \
           /opt/venv/bin/pip install ".[${EXTRAS}]"; \
       fi

# The real package. --no-deps because the layer above already resolved them, so this
# step stays cheap and cannot quietly pull a different version than the one tested.
COPY app ./app
COPY seed ./seed
RUN /opt/venv/bin/pip install --no-deps --force-reinstall .

# ------------------------------------------------------------------ runtime
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Runtime libraries only. WeasyPrint needs pango and cairo for PDF rendering; libpq5
# for psycopg. Everything else is deliberately absent to keep the attack surface small,
# because this image is scanned line by line in customer security reviews.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin aap

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=aap:aap . .

RUN mkdir -p /var/lib/aap/artifacts && chown -R aap:aap /var/lib/aap

USER 10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
