"""User settings in %APPDATA%\\Cratekeeper\\config.json (folder, API keys, options, language, accepted terms).

API keys are encrypted with Windows DPAPI (only this user on this PC can read them).
Never in the repo, never sent anywhere.
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
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


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


def _open_sealed(value):
    if not isinstance(value, str) or not value.startswith("dpapi:"):
        return value  # plain (older config or no DPAPI): re-sealed on next save
    dec = _dpapi(base64.b64decode(value[6:]), False)
    return dec.decode("utf-8") if dec else ""


def load():
    cfg = _read()
    known = {f.name for f in fields(Options)}
    opts = Options(**{k: v for k, v in cfg.get("opcoes", {}).items() if k in known})
    return opts, {k: _open_sealed(v) for k, v in cfg.get("chaves", {}).items()}


def save(opts, keys):
    cfg = _read()
    cfg.update(opcoes=asdict(opts), chaves={k: _seal(v) for k, v in keys.items()})
    _write(cfg)


def get(key, default=None):
    return _read().get(key, default)


def put(key, value):
    cfg = _read()
    cfg[key] = value
    _write(cfg)
