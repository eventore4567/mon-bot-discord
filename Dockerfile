FROM denoland/deno:bin-2.9.5 AS deno
FROM python:3.11-slim

# yt-dlp a désormais besoin d'un runtime JavaScript pour résoudre les challenges
# YouTube. Deno est le runtime recommandé et est activé par défaut par yt-dlp.
COPY --from=deno /deno /usr/local/bin/deno

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Barrière de syntaxe : aucune erreur Python dans les couches critiques ne doit
# atteindre le runtime Railway.
RUN python -m compileall -q core cogs web main.py railway_boot.py railway_ha_boot.py railway_ha_product_boot_v8.py

# Barrière de qualité micro-kernel exécutée à chaque build primaire : une release
# qui casse l'isolation, la readiness, les circuits ou le reload reste hors prod.
RUN python -m pytest -q \
    tests/test_module_kernel.py \
    tests/test_module_runtime.py \
    tests/test_module_supervisor.py \
    tests/test_module_gate.py \
    tests/test_module_policy.py \
    tests/test_health_runtime_module_readiness.py \
    tests/test_runtime_observability_module_health.py \
    tests/test_runtime_attribution.py \
    tests/test_tickets_autoclose_resilience.py \
    tests/test_ticket_open_concurrency.py \
    tests/test_logs_bulk_delete_resilience.py

# Port du dashboard web intégré (voir web/dashboard.py) — Railway fournit sa propre
# variable PORT au runtime, cette ligne ne sert que de documentation pour Docker.
EXPOSE 8080

# V98 installe la nouvelle arborescence slash puis délègue au bootstrap Railway historique.
# Le dashboard démarre toujours avant Discord afin de préserver le healthcheck existant.
CMD ["python3", "sentrix_v98_boot.py"]
