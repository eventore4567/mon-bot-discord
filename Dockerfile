FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY sentrix-platform/pyproject.toml ./
COPY sentrix-platform/libs ./libs
COPY sentrix-platform/services ./services
COPY sentrix-platform/agents ./agents
COPY sentrix-platform/migrations ./migrations
COPY sentrix-platform/ops ./ops
COPY sentrix-platform/README.md ./README.md

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

EXPOSE 8080

# Dedicated deployment branch: this image cannot start the Discord bot.
CMD ["python", "ops/bootstrap/production_control_plane.py"]
