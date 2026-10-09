FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY prompt ./prompt

RUN pip install --no-cache-dir .

ENV PROMPT_DATABASE_URL=postgresql://prompt:prompt@postgres:5432/prompt

CMD ["prompt-api"]
