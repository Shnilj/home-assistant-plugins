ARG BUILD_ARCH=amd64
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base-debian:bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /opt/stash

# Pure-Python dependencies only: no numpy, so no version pin is needed for the
# older CPUs the guide warns about. pip needs --break-system-packages on Debian.
COPY requirements.txt ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip jq \
    && pip3 install --no-cache-dir --break-system-packages -r requirements.txt \
    && apt-get purge -y --auto-remove python3-pip \
    && rm -rf /var/lib/apt/lists/*

# The UI is baked into the image: after a change, Reload + Update (rebuild),
# a restart alone keeps showing the old one.
COPY app/ ./app/

COPY run.sh /run.sh
RUN chmod a+x /run.sh

LABEL io.hass.name="Stash" \
      io.hass.description="Where your stuff is" \
      io.hass.type="addon" \
      io.hass.arch="aarch64|amd64|armv7"

CMD [ "/run.sh" ]
