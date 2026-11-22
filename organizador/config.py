"""User settings (folder, API keys, options) in %APPDATA%\\OrganizadorMusica\\config.json. Never in the repo."""
import json
import os
from dataclasses import asdict, fields

from .pipeline import APP_DIR, Options

PATH = os.path.join(APP_DIR, "config.json")


def load():
    try:
        with open(PATH, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = {}
    known = {f.name for f in fields(Options)}
    opts = Options(**{k: v for k, v in cfg.get("opcoes", {}).items() if k in known})
    return opts, cfg.get("chaves", {})


def save(opts, keys):
    os.makedirs(APP_DIR, exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"opcoes": asdict(opts), "chaves": keys}, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, PATH)
