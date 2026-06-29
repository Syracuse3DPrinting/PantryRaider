FROM python:3.12-slim

WORKDIR /app

# rclone powers the optional "push backup to a cloud remote" feature
# (Settings > Security > Backup). ca-certificates is needed for outbound HTTPS.
# This line is unchanged on purpose so its build-cache layer is reused and no
# apt fetch is needed on a rebuild.
RUN apt-get update \
    && apt-get install -y --no-install-recommends rclone ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# evtest lets the touchscreen calibration read raw taps from the panel's
# /dev/input device (the appliance compose mounts /dev/input in). It is a
# SEPARATE, best-effort layer: on a network that blocks the Debian mirror in the
# build (some captive or filtering proxies 401 plain-HTTP apt), the image still
# builds, just without on-device calibration, instead of failing the whole
# rebuild. When the mirror is reachable, evtest is installed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends evtest \
    && rm -rf /var/lib/apt/lists/* \
    || echo "WARN: evtest not installed (apt mirror unreachable); touch calibration will be unavailable"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN mkdir -p /app/data

# Production default: no --reload, code is baked into the image. The dev
# docker-compose.yml overrides this command to add --reload alongside a
# volume mount of ./service/app so `git pull` applies changes live.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
