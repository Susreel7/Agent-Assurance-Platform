FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY observe ./observe

RUN pip install --no-cache-dir .

ENV OBSERVE_OBJECT_STORE=local
ENV OBSERVE_OBJECT_STORE_ROOT=/var/lib/aap/observe/objects

# Default CMD is ingest; override for worker/query.
CMD ["observe-ingest"]
