# SentinelFlow API image.
#
# One image serves two roles in compose.yaml: the one-shot `migrate` job
# (`alembic upgrade head`) and the long-running `api`. Keeping them in a single
# image guarantees the schema is applied by exactly the code that will serve it.
#
# Build:  docker build -t sentinelflow-api .
# Run:    docker run --rm -p 8000:8000 --env-file .env sentinelflow-api

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Run as a fixed non-root uid so a bind-mounted volume has predictable
# ownership and the process cannot write to the image layer.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

# Dependencies first: this layer is cached until pyproject.toml changes.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

# Migration assets are needed by the `migrate` command.
COPY alembic.ini ./
COPY migrations ./migrations

# Synthetic sample logs, so the documented "import some data" step works from
# inside the container. No real events, no secrets.
COPY data ./data

USER app

EXPOSE 8000

# Liveness, not readiness: a database outage must not restart a healthy API.
# The compose file additionally probes /health/ready before routing traffic.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "sentinelflow.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
