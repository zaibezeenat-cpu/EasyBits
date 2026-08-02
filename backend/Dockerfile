# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Backend (FastAPI + Playwright). The Playwright base image already carries the
# system libraries Chromium needs, which is the hard part to reproduce.
# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Dependencies as their own layer so a code-only change does not reinstall them.
# `pip install .` needs the package source present, so app/ is copied first.
COPY pyproject.toml ./
COPY app ./app
RUN pip install . && playwright install chromium

# Remaining project files (scripts, migrations references, etc.).
COPY . .

# Never run as root. The Playwright image ships `pwuser`; create it if absent.
RUN id pwuser >/dev/null 2>&1 || useradd -m -u 1001 pwuser
RUN chown -R pwuser:pwuser /app
USER pwuser

EXPOSE 8000

# Liveness: /health returns 200 once the app has booted and config has loaded.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
