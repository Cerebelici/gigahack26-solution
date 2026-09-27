FROM python:3.14-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt .
RUN pip install -r requirements.txt

FROM python:3.14-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Wheels bundle GDAL, PROJ, and OR-Tools. They still load these from the system.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libbz2-1.0 \
        libexpat1 \
        libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY app ./app

# Default UPLOAD_DIR is the parent of this directory (/uploads).
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /uploads \
    && chown app:app /uploads

USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
