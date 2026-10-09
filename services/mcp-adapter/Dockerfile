FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY adapter ./adapter

FROM base AS test
RUN pip install --no-cache-dir pytest==8.4.2
COPY tests ./tests
RUN pytest -q

FROM base AS runtime
RUN useradd --create-home --uid 10001 adapter
USER adapter

EXPOSE 8097
CMD ["uvicorn", "adapter.app:app", "--host", "0.0.0.0", "--port", "8097"]
