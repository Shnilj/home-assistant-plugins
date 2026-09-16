ARG BUILD_ARCH=amd64
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base-debian:bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Pure-Python dependencies only: no numpy, so no version pin needed here.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip jq \
    && pip3 install --no-cache-dir --break-system-packages \
        "flask==3.0.3" \
        "waitress==3.0.0" \
    && apt-get purge -y --auto-remove python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/trippack
COPY app/ ./app/

COPY run.sh /run.sh
RUN chmod a+x /run.sh

LABEL io.hass.name="TripPack" \
      io.hass.description="Itinerary-driven packing lists" \
      io.hass.type="addon" \
      io.hass.arch="aarch64|amd64|armv7"

CMD [ "/run.sh" ]
