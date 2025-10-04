# 📚 Catalogerr

Catalogerr is a media cataloging and archive management tool designed to work alongside the Servarr ecosystem (Sonarr, Radarr, etc.).  
It indexes drives, enriches metadata from TMDB, and provides a Servarr-style dashboard.

---

## ⚙️ Setup Instructions

Before running Catalogerr, you **must create a `.env` file** in the project root with the following environment variables:

```env
# --- Sonarr Integration ---
SONARR_URL=http://<your-sonarr-host>:8989
SONARR_API_KEY=<your-sonarr-api-key>

# --- Radarr Integration ---
RADARR_URL=http://<your-radarr-host>:7878
RADARR_API_KEY=<your-radarr-api-key>

# --- Application Secrets ---
APP_API_KEY=<random-secret-key>
TMDB_API_KEY=<your-tmdb-api-key>

# --- Admin Login ---
ADMIN_USER=admin
ADMIN_PASSWORD=<choose-a-strong-password>

# --- Database ---
DB_FILE=index.db

# --- Application Metadata ---
APP_NAME=Catalogerr
APP_VERSION=1.0.0
INSTANCE_NAME=MyServer

# --- Runtime Information (for system status endpoint) ---
RUNTIME_VERSION=Python 3.12
OS_NAME=Ubuntu
OS_VERSION=22.04
```

---

## 📂 Config.yaml

In addition to the `.env` file, you also need to create a `config.yaml` to define the media paths Catalogerr should index:

```yaml
parent_paths:
  - name: movies
    path: /path/to/movies
  - name: tvshows
    path: /path/to/tvshows
  - name: archive
    path: /path/to/archive
```

---

## 🚀 Initialization

After creating the `.env` and `config.yaml`, you must run the **init script** before starting the server:

```bash
python3 init.py
```

This will initialize the database and prepare the environment.  

Then start the main server:

```bash
python3 main.py
```

---

## 🖥️ Features

- 📦 Drive indexing and storage tracking  
- 🎬 Metadata enrichment via TMDB  
- 🖼️ Automatic poster caching (local storage)  
- 📊 Dashboard styled after the Servarr ecosystem  

---
