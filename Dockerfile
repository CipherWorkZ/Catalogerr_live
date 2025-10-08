FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy your code into the container
COPY . .

# Install bash (needed for init.sh)
RUN apt-get update && apt-get install -y bash && rm -rf /var/lib/apt/lists/*

# Entrypoint script will control flow
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
