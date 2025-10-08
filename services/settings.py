def get_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        cfg = {}
    return jsonify(cfg)


def save_config():
    data = request.get_json(force=True)
    parent_paths = data.get("parent_paths", [])
    with open(CONFIG_FILE, "w") as f:
        yaml.safe_dump({"parent_paths": parent_paths}, f)
    return jsonify({"status": "saved", "parent_paths": parent_paths})