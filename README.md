<p align="center">
  <img src="https://github.com/CipherWorkZ/Catalogerr_live/blob/main/static/logo/logo.png" alt="Catalogerr Logo" width="120"/>
</p>

Catalogerr is a **media cataloging and archive management tool** built to work alongside the Servarr ecosystem (Sonarr, Radarr, etc.).  

Unlike Sonarr and Radarr, which manage only **active libraries**, Catalogerr gives you a **single hub for your entire collection** — including:  
- Active drives  
- Archived content  
- Cold storage and backups  

It enriches metadata using **TMDB**, tracks backup status, and provides clear **collection stats** — all inside a familiar **Servarr-style dashboard**.  

---

## 🌟 About Catalogerr  

Catalogerr makes it easy to know where everything lives — from active drives to cold storage — while giving you **clear insights and tools** to keep your collection healthy.  

### Our Mission  
Media managers like Sonarr and Radarr focus on **active content**. Catalogerr goes further:  
it unifies **active, archived, and backup media** into a **single source of truth**.  

### What Makes Catalogerr Different  
- 📚 Tracks **active, archive, and cold-storage** drives in one place  
- 🔗 Integrates seamlessly with **Sonarr/Radarr** (ARR ecosystem)  
- 📊 Provides **stats & health insights** across your entire collection  
- ⚡ Built for **automation & transparency** from the ground up  

---

## 🚀 Roadmap & Release Status  

- **Phase 1: Core Catalog & Archive (✅ Done)**  
  - Drive scanning by serial #  
  - Media indexing & catalog views  
  - Initial Sonarr/Radarr metadata import (read-only)  
  - Foundations for cold storage tracking  

- **Phase 2: Stats & Backup Awareness (✅ Done)**  
  - Collection dashboards (sizes, counts, trends)  
  - Backup status tracking (see what is and isn’t backed up)  
  - Extended Sonarr/Radarr connectors (still read-only)  

🎉 **Goal Achieved:** First stable release — **Catalogerr v1.0.0**  

- **Phase 3: Connector Ecosystem (🚧 In Progress)**  
  - Apps page for Sonarr/Radarr/Lidarr/etc.  
  - Queue, diskspace, and system health from connected apps  
  - API-driven connector syncs  

---

## ⚙️ Setup Instructions  

Before running Catalogerr, you must create a **`.env` file** in the project root with the following environment variables:  

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
APP_VERSION=1.1.1
INSTANCE_NAME=MyServer

# --- Runtime Information (for system status endpoint) ---
RUNTIME_VERSION=Python 3.12
OS_NAME=Ubuntu
OS_VERSION=22.04
```

---

## 📂 config.yaml  

Alongside `.env`, you must also create a **`config.yaml`** file to define which media paths Catalogerr should index:  

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

## 🚀 Initialization & Running  

After preparing `.env` and `config.yaml`, run the **initialization script**:  

```bash
python3 admin.py
```

This will create the database schema and prepare the environment.  

Then start the server with:  

```bash
python3 main.py
```

Or run in production with **Gunicorn**:  

```bash
gunicorn -w 4 -b 0.0.0.0:8000 main:app
```

By default, the app runs on **http://localhost:8000** (unless configured otherwise).  

---

## 🖥️ Features  

- 📦 Drive indexing & storage tracking  
- 🎬 Metadata enrichment via TMDB  
- 🖼️ Local poster caching  
- 📊 Collection dashboards (sizes, counts, trends)  
- 💾 Backup awareness (track what is and isn’t backed up)  
- 🔌 Connector ecosystem (Sonarr/Radarr integration, queue, diskspace)  
- 📑 Dashboard styled after the Servarr ecosystem  
- ⚙️ Settings editor for `.env` and `config.yaml`  
- 🗄️ Backup/restore with a single click  
- 📜 Built-in Changelog viewer  

---

## 🗂️ Project Structure  

```
Catalogerr_live/
├── routes/         # Flask blueprints (catalog, system, tasks, stats, auth, connectors, etc.)
├── services/       # Core logic (auth, tasks, jobs, settings, stats, utils)
├── modules/        # Connector + poster handling
├── static/         # Shared static files (js/api.js, logos, posters)
├── templates/      # Jinja2 templates (dashboard, catalog, tasks, settings, stats, changelog)
├── admin.py        # Initialization script
├── main.py         # Flask app entrypoint
└── config.yaml     # Media paths config
```

---

## 🤝 Get Involved  

Catalogerr is being built **openly**.  
Follow our progress, share feedback, and contribute on GitHub to help shape its future.  

- GitHub: [CipherWorkZ/Catalogerr_live](https://github.com/CipherWorkZ/Catalogerr_live)  

---

## 📄 License  

This project is licensed under the **GNU GPL-3.0 License**.  
See the [LICENSE](LICENSE) file for details.  
