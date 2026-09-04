#!/usr/bin/with-contenv bashio
# ---------------------------------------------------------------------------
# CatWatch launcher.
# Pulls the MQTT broker connection from the Supervisor "mqtt" service (so it
# just works with the Mosquitto add-on) and hands control to the Python app.
# The rest of the configuration is read by the app from /data/options.json.
# ---------------------------------------------------------------------------
set -e

if bashio::services.available "mqtt"; then
    export MQTT_HOST="$(bashio::services mqtt "host")"
    export MQTT_PORT="$(bashio::services mqtt "port")"
    export MQTT_USER="$(bashio::services mqtt "username")"
    export MQTT_PASSWORD="$(bashio::services mqtt "password")"
    bashio::log.info "Using MQTT broker at ${MQTT_HOST}:${MQTT_PORT}"
else
    bashio::log.warning "No MQTT service found. Install/configure the Mosquitto broker add-on."
fi

export LOG_LEVEL="$(bashio::config 'log_level')"

cd /app
exec python3 -m app.main
