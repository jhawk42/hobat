
# Stage 1: Build Python packages on the Home Assistant add-on base
FROM ghcr.io/home-assistant/base:latest AS builder

# Install system build dependencies
RUN apk add --no-cache python3 python3-dev gcc musl-dev libffi-dev py3-pip

# Create and activate virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies (compiled against musl when no Alpine wheel exists)
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# Stage 2: Home Assistant add-on runtime stage
FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION=0.1.0
LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="aarch64|amd64"

# Install runtime Python, Bash, and the Docker CLI
RUN apk add --no-cache python3 bash docker-cli

# Copy the pre-compiled virtual environment from the builder
COPY --from=builder /opt/venv /opt/venv

# Force the container to use the virtual environment by default
ENV PATH="/opt/venv/bin:$PATH"

# Set the working directory inside the container
WORKDIR /app

# Copy and set permissions for the run script
COPY addon_hobat/run.sh /run.sh
RUN chmod a+x /run.sh

# Copy the application code
COPY src /app/src

# Set the working directory to where td_cli.py is located
WORKDIR /app/src

# Set environment variables
ENV APP_DIR=/app/src
ENV SCRIPT_NAME=td_webserver.py
ENV HOST=0.0.0.0
ENV TD_DATA_DIR=/data

# Command to run the script
CMD [ "/run.sh" ]
