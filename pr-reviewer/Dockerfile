FROM --platform=linux/amd64 python:3.12-slim-bookworm AS builder

WORKDIR /app
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Runtime ──────────────────────────────────────────────────────────
FROM --platform=linux/amd64 python:3.12-slim-bookworm

WORKDIR /app

# Create non-root user
RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app

COPY --from=builder /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY src/ ./src/

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python", "-m", "src.main"]
