FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY libs ./libs
COPY services ./services
COPY agents ./agents
COPY migrations ./migrations
COPY ops ./ops
COPY README.md ./README.md

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

EXPOSE 8080

CMD ["python", "ops/bootstrap/production_control_plane.py"]
