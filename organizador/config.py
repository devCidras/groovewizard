"""User settings in %APPDATA%\\GrooveWizard\\config.json (folder, API keys, options, language, accepted terms).

API keys are encrypted with Windows DPAPI when available (only this Windows user on this PC can read them); if DPAPI
fails they are stored as plain text. They never go into the repo and are only sent to their own service (Discogs /
Last.fm) when looking up genres or pressing Check.
"""
import base64
import ctypes
import json
import os
from dataclasses import asdict, fields

from .pipeline import APP_DIR, Options

PATH = os.path.join(APP_DIR, "config.json")


def _read():
    try:
        with open(PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except ValueError:  # damaged JSON: kept as config.json.estragado, settings start over
        try:
            os.replace(PATH, PATH + ".estragado")
        except OSError:
            pass
        return {}
    except OSError:
        return None  # transient lock / antivirus: never rename or overwrite the existing config


def _write(cfg):
    os.makedirs(APP_DIR, exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, PATH)


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data, protect):
    """Windows DPAPI: only this Windows user on this PC can decrypt. None if unavailable."""
    try:
        crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    except AttributeError:  # not Windows
        return None
    src = _Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(out)):  # 0x1: no UI
        return None
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def _seal(value):
    if not value:
        return value
    enc = _dpapi(value.encode("utf-8"), True)
    return "dpapi:" + base64.b64encode(enc).decode() if enc else value


_UNREADABLE = {}  # key name -> sealed value this Windows user can't open (other PC / profile): kept, never wiped


def _open_sealed(value, name=""):
    if not isinstance(value, str) or not value.startswith("dpapi:"):
        return value  # plain (older config or no DPAPI): re-sealed on next save
    try:
        dec = _dpapi(base64.b64decode(value[6:]), False)
        return dec.decode("utf-8") if dec else _keep(name, value)
    except (ValueError, UnicodeDecodeError):
        return _keep(name, value)


def _keep(name, value):
    if name:
        _UNREADABLE[name] = value
    return ""


def load():
    cfg = _read() or {}
    defaults = Options()
    known = {f.name: getattr(defaults, f.name) for f in fields(Options)}
    saved = cfg.get("opcoes") if isinstance(cfg.get("opcoes"), dict) else {}
    keys = cfg.get("chaves") if isinstance(cfg.get("chaves"), dict) else {}
    valid = {k: v for k, v in saved.items() if k in known and type(v) is type(known[k])}
    if "protected" in valid:
        valid["protected"] = [p for p in valid["protected"] if isinstance(p, str)]
    opts = Options(**valid)
    return opts, {k: _open_sealed(v, k) for k, v in keys.items() if isinstance(v, str)}


def save(opts, keys):
    cfg = _read()
    if cfg is None:
        return False  # do not replace a temporarily unreadable config with defaults
    for k, v in keys.items():
        if v:
            _UNREADABLE.pop(k, None)  # replaced by a new key: the old unreadable one is gone for good
    # a key that couldn't be opened and is still empty in the window keeps its old sealed value
    cfg.update(opcoes=asdict(opts), chaves={k: (_UNREADABLE[k] if not v and k in _UNREADABLE else _seal(v))
                                            for k, v in keys.items()})
    _write(cfg)
    return True


def clear_key(name):
    """Explicitly forget a key, including a sealed value this Windows profile cannot decrypt."""
    cfg = _read()
    if cfg is None:
        return False
    _UNREADABLE.pop(name, None)
    keys = cfg.get("chaves") if isinstance(cfg.get("chaves"), dict) else {}
    keys.pop(name, None)
    cfg["chaves"] = keys
    _write(cfg)
    return True


def get(key, default=None):
    cfg = _read()
    return cfg.get(key, default) if cfg is not None else default


def put(key, value):
    cfg = _read()
    if cfg is None:
        return False
    cfg[key] = value
    _write(cfg)
    return True
