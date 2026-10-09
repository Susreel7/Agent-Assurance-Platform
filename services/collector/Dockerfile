# The collector runs inside the customer's network, so it is kept deliberately minimal.
# A short dependency list and a small image make for a far shorter security review than
# the API image, which carries a PDF renderer, cloud SDKs and database drivers.
#
# Keep it that way. If a change here needs a heavyweight dependency, it belongs in the
# control plane instead.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin aap

WORKDIR /app
COPY pyproject.toml ./

# Dependencies first, keyed on pyproject.toml alone so editing source does not reinstall
# them. setuptools declares `packages = ["collector"]` explicitly and will not build
# metadata without that directory, so it is stubbed here and replaced below.
RUN mkdir -p collector \
    && touch collector/__init__.py \
    && pip install --upgrade pip \
    && pip install .

COPY --chown=aap:aap . .

# The real package, over the stub. --no-deps because the layer above resolved them.
RUN pip install --no-deps --force-reinstall .

RUN mkdir -p /var/lib/aap/collector/spool && chown -R aap:aap /var/lib/aap

USER 10001

EXPOSE 4318

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:4318/healthz')"

CMD ["uvicorn", "collector.main:app", "--host", "0.0.0.0", "--port", "4318"]
