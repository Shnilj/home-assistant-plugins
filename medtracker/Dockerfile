# Base image is selected per architecture. BUILD_ARCH is provided by the Home
# Assistant builder; the amd64 default keeps the image buildable standalone.
# A Debian base (matching the other add-ons in this repo) keeps the runtime
# consistent; MedTracker has no compiled dependencies (pure-Python wheels), so
# no numpy/opencv pinning is needed.
ARG BUILD_ARCH=amd64
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base-debian:bookworm

LABEL org.opencontainers.image.title="MedTracker" \
      org.opencontainers.image.description="Per-person/animal medication scheduling and adherence for Home Assistant" \
      org.opencontainers.image.source="https://github.com/Shnilj/home-assistant-plugins"

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

# Application code.
COPY app /app/app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /app
CMD [ "/run.sh" ]
