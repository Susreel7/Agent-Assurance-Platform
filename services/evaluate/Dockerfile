FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY evaluate ./evaluate

RUN pip install --no-cache-dir .

ENV EVALUATE_DATABASE_URL=postgresql://evaluate:evaluate@postgres:5432/evaluate

CMD ["evaluate-api"]
