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

# Démarre d'abord le serveur HTTP du dashboard, puis le bot Discord. Cela évite les
# 502 Railway pendant que les cogs et les commandes slash terminent leur initialisation.
CMD ["python3", "railway_boot.py"]
