<p align="center">
  <img src="https://github.com/CipherWorkZ/Catalogerr_live/blob/main/static/logo/logo.png" alt="Catalogerr Logo" width="120"/>
</p>

<p align="center">
  <a href="https://github.com/CipherWorkZ/Catalogerr_live/releases">
    <img src="https://img.shields.io/github/v/release/CipherWorkZ/Catalogerr_live" alt="GitHub release">
  </a>
  <a href="https://github.com/CipherWorkZ/Catalogerr_live/stargazers">
    <img src="https://img.shields.io/github/stars/CipherWorkZ/Catalogerr_live" alt="GitHub stars">
  </a>
  <a href="https://github.com/CipherWorkZ/Catalogerr_live/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/CipherWorkZ/Catalogerr_live" alt="License">
  </a>
  <a href="https://hub.docker.com/r/patgames36/catalogerr">
    <img src="https://img.shields.io/docker/pulls/patgames36/catalogerr" alt="Docker Pulls">
  </a>
</p>

# Catalogerr – Backup & Archive Tool for Sonarr, Radarr, and Jellyfin

**Website:** https://catalogerr.patserver.com

Catalogerr is a **self-hosted media cataloging and backup management tool** designed to complement the **Servarr ecosystem** (Sonarr, Radarr, Lidarr) and **media servers** like Jellyfin and Plex.

Unlike Sonarr and Radarr, which manage only **active libraries**, Catalogerr gives you a **single hub for your entire collection** — including:
- Active drives
- Archived content
- Cold storage and backups

It enriches metadata using **TMDB**, tracks backup status, and provides clear **collection stats** — all inside a familiar **Servarr-style dashboard**.

---

## Use Cases

-  **Backup Sonarr & Radarr libraries** — Keep an indexed record of movies/shows for recovery.
-  **Archive cold-storage drives** — Track exactly what’s on offline/backup disks.
-  **Integrate with Jellyfin/Plex** — Enrich the catalog with TMDB metadata & posters.
-  **Analyze collection health** — Redundancy, utilization, and per-drive stats.
-  **Disaster recovery** — Restore knowledge of your library after DB loss/corruption.
-  **Connector-aware** — Pull media info from Sonarr/Radarr and cache artwork reliably.

---

##  About Catalogerr

Catalogerr makes it easy to know where everything lives — from active drives to cold storage — while giving you **clear insights and tools** to keep your collection healthy.

### Our Mission
Media managers like Sonarr and Radarr focus on **active content**. Catalogerr goes further:
it unifies **active, archived, and backup media** into a **single source of truth**.

### What Makes Catalogerr Different
-  Tracks **active, archive, and cold-storage** drives in one place
-  Integrates seamlessly with **Sonarr/Radarr** (ARR ecosystem)
-  Provides **stats & health insights** across your entire collection
-  Built for **automation & transparency** from the ground up

---

##  Roadmap & Release Status

- **Phase 1: Core Catalog & Archive (✅ Done)**
- **Phase 2: Stats & Backup Awareness (✅ Done)**
- **Phase 3: Connector Ecosystem (🚧 In Progress)**

 **Latest Release:** see the badge above for the current version.

---

##  Installation (New in v1.1.3)

Catalogerr now ships with an **installer script** that sets up everything for you.  

Run:

```bash
curl -sSL https://raw.githubusercontent.com/CipherWorkZ/Catalogerr_live/main/install.sh | sudo bash
```

The installer will:
-  Download the latest release archive
-  Create `/etc/Catalogerr_live` with proper permissions
-  Generate `.env` and `config.yaml`
-  Prompt you for an admin password
-  Run `admin.py` to seed the database
-  Create and enable `catalogerr-api.service` (systemd, Gunicorn)

 Installer is **still experimental** — please test and report issues.

---

##  Manual Setup Instructions

If you prefer manual setup, create a **`.env`** file in the project root:

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
APP_VERSION=1.1.3
INSTANCE_NAME=MyServer

# --- Runtime Information (for system status endpoint) ---
RUNTIME_VERSION=Python 3.12
OS_NAME=Ubuntu
OS_VERSION=22.04
```

---

##  config.yaml

Define which media paths Catalogerr should index:

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

##  Initialization & Running

After preparing `.env` and `config.yaml`, seed the database:

```bash
python3 admin.py
```

Then run the server:

```bash
python3 main.py
```

Or in production with **Gunicorn**:

```bash
gunicorn -w 4 -b 0.0.0.0:8008 main:app
```

If installed via `install.sh`, Catalogerr will already be running under **systemd**:
```bash
systemctl status catalogerr-api.service
```

---

##  Features

-  Drive indexing & storage tracking
-  Metadata enrichment via TMDB
-  Poster caching
-  Collection dashboards
-  Backup awareness
-  ARR ecosystem connectors
-  Servarr-style dashboard
-  Backup/restore support
-  Built-in Changelog viewer
-  Auto-installer (systemd + Gunicorn)

---

##  Project Structure

```
Catalogerr_live/
├── routes/         # Flask blueprints (catalog, system, tasks, stats, auth, connectors, etc.)
├── services/       # Core logic (auth, tasks, jobs, settings, stats, utils)
├── modules/        # Connector + poster handling
├── static/         # Shared static files (js/api.js, logos, posters)
├── templates/      # Jinja2 templates (dashboard, catalog, tasks, settings, stats, changelog)
├── admin.py        # Initialization script
├── install.sh      # Auto installer (v1.1.3+)
├── main.py         # Flask app entrypoint
└── config.yaml     # Media paths config
```

---

##  Get Involved

Catalogerr is being built **openly**.  
Follow our progress, share feedback, and contribute on GitHub to help shape its future.  

- GitHub: [CipherWorkZ/Catalogerr_live](https://github.com/CipherWorkZ/Catalogerr_live)

---

##  License

This project is licensed under the **GNU GPL-3.0 License**.  
See the [LICENSE](LICENSE) file for details.
