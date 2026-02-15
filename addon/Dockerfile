# Home Assistant CEZ PND Add-on Dockerfile
ARG BUILD_ARCH=amd64
FROM python:3.11-alpine

# Set maintainer
LABEL maintainer="Martin Horak <martin@example.com>"

# Install required system packages
RUN apk add --no-cache \
    gcc \
    musl-dev \
    libffi-dev \
    openssl-dev

# Install required Python packages
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application source code
COPY src/ /app/src/

COPY config.yaml /
COPY run.sh /
RUN chmod +x /run.sh

# Create non-root user
RUN addgroup -g 1000 hass && \
    adduser -u 1000 -G hass -s /bin/sh -D hass

# Set working directory
WORKDIR /app

# Set permissions
RUN chown -R hass:hass /app

# Switch to non-root user
USER hass

# Set the entrypoint
CMD ["/run.sh"]