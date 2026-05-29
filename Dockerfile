# Use an official Python runtime based on Debian Slim for a small image size
FROM python:3.14-slim-bookworm

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install the Docker CLI from Docker's official apt repository
RUN apt-get update && apt-get install -y --no-install-recommends \
	ca-certificates \
	curl \
	gnupg \
	&& install -m 0755 -d /etc/apt/keyrings \
	&& curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
	&& chmod a+r /etc/apt/keyrings/docker.asc \
	&& echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
	&& apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
	&& rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Copy init script to the container
COPY rootfs /

# Copy the requirements file and install dependencies
# Doing this before copying the rest of the code improves build caching
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Set the working directory to where td_cli.py is located  
WORKDIR /app/src

# Set environment variables
ENV APP_DIR=/app/src
ENV SCRIPT_NAME=td_webserver.py
ENV HOST=0.0.0.0

# Command to run the script via init
CMD ["/init"]
