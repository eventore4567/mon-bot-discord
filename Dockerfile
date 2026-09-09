FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Port du dashboard web intégré (voir web/dashboard.py) — Railway fournit sa propre
# variable PORT au runtime, cette ligne ne sert que de documentation pour Docker.
EXPOSE 8080

# V98 installe la nouvelle arborescence slash puis délègue au bootstrap Railway historique.
# Le dashboard démarre toujours avant Discord afin de préserver le healthcheck existant.
CMD ["python3", "sentrix_v98_boot.py"]
