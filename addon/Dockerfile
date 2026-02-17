# Home Assistant CEZ PND Add-on Dockerfile
ARG BUILD_ARCH=amd64
FROM python:3.11-slim

# Set maintainer
LABEL maintainer="Martin Horak <martin@example.com>"

# Install required system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libatspi2.0-0 \
    ca-certificates \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Install required Python packages
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

# Install Playwright browsers
RUN playwright install chromium --with-deps

# Copy application source code
COPY src/ /app/src/

COPY config.yaml /
COPY run.sh /
RUN chmod +x /run.sh

# Create non-root user
RUN groupadd -g 1000 hass && \
    useradd -u 1000 -g hass -s /bin/bash -m hass

# Set working directory
WORKDIR /app

# Set permissions
RUN chown -R hass:hass /app

# Switch to non-root user
USER hass

# Set the entrypoint
CMD ["/run.sh"]