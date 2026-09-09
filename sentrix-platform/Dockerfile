FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY libs ./libs
COPY services ./services
COPY agents ./agents
COPY README.md ./README.md

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

EXPOSE 8080

CMD ["sh", "-c", "uvicorn services.companion.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
