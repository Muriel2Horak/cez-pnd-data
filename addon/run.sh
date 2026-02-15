#!/usr/bin/with-bashio

# HA Supervisor CEZ PND Add-on Startup Script
# Uses bashio to read configuration and set environment variables

# Read CEZ credentials from add-on configuration
export CEZ_EMAIL=$(bashio::config 'email')
export CEZ_PASSWORD=$(bashio::config 'password')
export CEZ_ELECTROMETER_ID=$(bashio::config 'electrometer_id')

# Read MQTT connection details from services
export MQTT_HOST=$(bashio::services 'mqtt' 'host')
export MQTT_PORT=$(bashio::services 'mqtt' 'port')
export MQTT_USER=$(bashio::services 'mqtt' 'username')
export MQTT_PASSWORD=$(bashio::services 'mqtt' 'password')

# Log startup information (excluding password)
bashio::log.info "Starting CEZ PND add-on..."
bashio::log.info "Email: ${CEZ_EMAIL}"
bashio::log.info "Electrometer ID: ${CEZ_ELECTROMETER_ID}"
bashio::log.info "MQTT Host: ${MQTT_HOST}:${MQTT_PORT}"

# Wait for MQTT service to be available
bashio::log.info "Waiting for MQTT service..."
bashio::wait.for_service mqtt

# Start the main Python application
bashio::log.info "Starting main application..."
exec python3 /app/src/main.py