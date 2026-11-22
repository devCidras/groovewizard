"""User settings in %APPDATA%\\Cratekeeper\\config.json (folder, API keys, options, language, accepted terms).

Never in the repo, never sent anywhere.
"""
import json
import os
from dataclasses import asdict, fields

from .pipeline import APP_DIR, Options

PATH = os.path.join(APP_DIR, "config.json")


def _read():
    try:
        with open(PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write(cfg):
    os.makedirs(APP_DIR, exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, PATH)


def load():
    cfg = _read()
    known = {f.name for f in fields(Options)}
    opts = Options(**{k: v for k, v in cfg.get("opcoes", {}).items() if k in known})
    return opts, cfg.get("chaves", {})


def save(opts, keys):
    cfg = _read()
    cfg.update(opcoes=asdict(opts), chaves=keys)
    _write(cfg)


def get(key, default=None):
    return _read().get(key, default)


def put(key, value):
    cfg = _read()
    cfg[key] = value
    _write(cfg)
