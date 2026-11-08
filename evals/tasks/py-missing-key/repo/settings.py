def load_settings(raw):
    return {"host": raw.get("host", "localhost"), "timeout": int(raw["timeout"])}
