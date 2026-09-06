# Base image is selected per architecture. BUILD_ARCH is provided by the Home
# Assistant builder; the amd64 default keeps the image buildable standalone.
# A Debian base (not the Alpine default) is required so numpy / opencv install
# from prebuilt manylinux wheels instead of compiling against musl.
ARG BUILD_ARCH=amd64
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base-debian:bookworm

LABEL org.opencontainers.image.title="CatWatch" \
      org.opencontainers.image.description="Local motion-triggered cat recognition for Home Assistant" \
      org.opencontainers.image.source="https://github.com/Shnilj/home-assistant-plugins"

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Python + the shared libraries OpenCV needs at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        libgl1 \
        libglib2.0-0 \
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
