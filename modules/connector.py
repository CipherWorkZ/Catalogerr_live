# connector.py
import yaml
import os
import requests

CONFIG_FILE = "connector.yaml"


def load_connectors():
    """Load connector config from YAML (return empty dict if missing)."""
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f) or {}


def save_connectors(cfg):
    """Save connector config back to YAML."""
    with open(CONFIG_FILE, "w") as f:
        yaml.safe_dump(cfg, f)


def test_connection(base_url, api_key, app_type="radarr"):
    """
    Test connection to Radarr/Sonarr by calling /system/status.
    Returns dict with success, version, and message.
    """
    base_url = base_url.rstrip("/")  # normalize URL

    try:
        resp = requests.get(
            f"{base_url}/api/v3/system/status",
            headers={"X-Api-Key": api_key},
            timeout=5
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "success": True,
            "app": app_type,
            "version": data.get("version"),
            "message": f"Connected to {app_type.title()} {data.get('version', 'unknown')}"
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "app": app_type,
            "error": str(e),
            "message": f"Failed to connect to {app_type.title()} at {base_url}"
        }
