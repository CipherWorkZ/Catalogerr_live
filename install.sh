#!/bin/bash
set -e

RELEASE_URL="https://github.com/CipherWorkZ/Catalogerr_live/releases/download/v1.1.3/V1.1.3.zip"
TMP_DIR="/tmp/catalogerr_install"
INSTALL_DIR="/etc/Catalogerr_live"
SERVICE_PATH="/etc/systemd/system/catalogerr-api.service"

# Detect install user (prioritize sudo user, fallback to current)
INSTALL_USER="${SUDO_USER:-$USER}"
INSTALL_GROUP=$(id -gn "$INSTALL_USER")

# Detect gunicorn binary for the install user
GUNICORN_BIN=$(sudo -u "$INSTALL_USER" which gunicorn 2>/dev/null || which gunicorn)

echo "📦 Catalogerr Installer v1.1.3"
echo "-----------------------------------"
echo "➡️ Detected install user: $INSTALL_USER ($INSTALL_GROUP)"
echo "➡️ Using gunicorn binary: $GUNICORN_BIN"

# 1. Prepare tmp dir
echo "➡️ Preparing temp directory..."
rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"

# 2. Download release zip
echo "➡️ Downloading release package..."
wget -q "$RELEASE_URL" -O "$TMP_DIR/build_V1.1.3.zip"

# 3. Unzip
echo "➡️ Extracting package..."
unzip -q "$TMP_DIR/build_V1.1.3.zip" -d "$TMP_DIR"

# 4. Create install directory
echo "➡️ Setting up install directory..."
rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

# 5. Copy files
echo "➡️ Copying files to $INSTALL_DIR..."
cp -r "$TMP_DIR"/Catalogerr_live/* "$INSTALL_DIR"/

# 5b. Ensure config.yaml exists
if [ ! -f "$INSTALL_DIR/config.yaml" ]; then
    echo "➡️ Creating default config.yaml..."
    cat > "$INSTALL_DIR/config.yaml" <<EOL
parent_paths:
  - name: movies
    path: /path/to/movies
  - name: tvshows
    path: /path/to/tvshows
  - name: archive
    path: /path/to/archive
EOL
fi

# 5c. Ensure .env exists
if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo "➡️ Creating default .env..."
    cat > "$INSTALL_DIR/.env" <<EOL
# --- Sonarr Integration ---
SONARR_URL=http://localhost:8989
SONARR_API_KEY=

# --- Radarr Integration ---
RADARR_URL=http://localhost:7878
RADARR_API_KEY=

# --- Application Secrets ---
APP_API_KEY=$(openssl rand -hex 16)
TMDB_API_KEY=

# --- Admin Login ---
# Leave blank – create your admin after install
ADMIN_USER=
ADMIN_PASSWORD=

# --- Database ---
DB_FILE=index.db

# --- Application Metadata ---
APP_NAME=Catalogerr
APP_VERSION=1.1.3
INSTANCE_NAME=$(hostname)

# --- Runtime Information ---
RUNTIME_VERSION=$(python3 --version 2>&1)
OS_NAME=$(lsb_release -si 2>/dev/null || echo Linux)
OS_VERSION=$(lsb_release -sr 2>/dev/null || uname -r)
EOL
fi

# 6. Permissions
echo "➡️ Setting permissions for $INSTALL_USER:$INSTALL_GROUP ..."
chown -R "$INSTALL_USER:$INSTALL_GROUP" "$INSTALL_DIR"
chmod -R 775 "$INSTALL_DIR"

mkdir -p "$INSTALL_DIR/static/poster"
mkdir -p "$INSTALL_DIR/backups"
chown -R "$INSTALL_USER:$INSTALL_GROUP" "$INSTALL_DIR/static" "$INSTALL_DIR/backups"
chmod -R 770 "$INSTALL_DIR/static" "$INSTALL_DIR/backups"

# 7. Create systemd service dynamically
echo "➡️ Creating systemd service at $SERVICE_PATH ..."
cat > "$SERVICE_PATH" <<EOL
[Unit]
Description=Catalogerr API + Scheduler (Gunicorn, threaded)
After=network.target

[Service]
User=$INSTALL_USER
Group=$INSTALL_GROUP
WorkingDirectory=$INSTALL_DIR
ExecStart=$GUNICORN_BIN main:app --workers 1 --threads 8 --worker-class gthread --timeout 180 --bind 0.0.0.0:8008
Restart=always
RestartSec=5
Environment="FLASK_ENV=production"
EnvironmentFile=-$INSTALL_DIR/.env

[Install]
WantedBy=multi-user.target
EOL

# 8. Enable service (don’t start it yet)
sudo systemctl daemon-reload
sudo systemctl enable catalogerr-api.service

# 9. Cleanup
echo "➡️ Cleaning up temp files..."
rm -rf "$TMP_DIR"

echo "✅ Catalogerr v1.1.3 installed successfully!"
echo
echo "⚡ Next steps:"
echo "1. Create your first admin user:"
echo "   cd $INSTALL_DIR && sudo -u $INSTALL_USER python3 admin.py"
echo
echo "2. Once admin is created, start the service:"
echo "   sudo systemctl start catalogerr-api.service"
echo
echo "3. Then access Catalogerr at: http://<your-server-ip>:8008"
