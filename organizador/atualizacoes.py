"""Update check: asks GitHub for the latest release and, on request, downloads its installer.

Only one request to api.github.com at start-up (no personal data). Silent on any failure: no internet, private
repo (404), rate limit... the app simply works without telling anyone.
"""
import hashlib
import json
import os
import re
import tempfile
import urllib.request

from . import __version__

REPO = "devCidras/groovewizard"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
UA = f"GrooveWizard/{__version__}"


def parse(v):
    """'v1.0.10' -> (1, 0, 10); anything odd -> ()."""
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3])


def newer(remote, local=__version__):
    return bool(parse(remote)) and parse(remote) > parse(local)


def check(timeout=6):
    """-> {"version", "page", "installer", "notes"} when a newer release exists, else None."""
    try:
        req = urllib.request.Request(API, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            rel = json.load(r)
    except Exception:
        return None
    if rel.get("draft") or rel.get("prerelease") or not newer(rel.get("tag_name", "")):
        return None
    setup = next((a for a in rel.get("assets", []) if re.search(r"setup\.exe$", a.get("name", ""), re.I)), None)
    sha = re.search(r"SHA-256:\s*`?([0-9a-fA-F]{64})", rel.get("body", "") or "")
    return {"version": rel["tag_name"].lstrip("v"), "page": rel.get("html_url", f"https://github.com/{REPO}/releases"),
            "installer": setup and setup.get("browser_download_url"), "sha256": sha and sha.group(1).lower(),
            "notes": rel.get("body", "")}


def download(url, sha256, progress=None):
    """Installer -> %TEMP%, only from github.com, and only kept if its SHA-256 matches the one in the release notes
    (the app never runs an installer it could not verify)."""
    if not re.match(r"^https://(github\.com|objects\.githubusercontent\.com)/", url or ""):
        raise ValueError("unexpected download address")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        raise ValueError("release has no SHA-256 to check against")
    dst = os.path.join(tempfile.gettempdir(), os.path.basename(url.split("?")[0]))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r, open(dst + ".part", "wb") as fh:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        h = hashlib.sha256()
        while chunk := r.read(1 << 16):
            fh.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if h.hexdigest() != sha256:
        os.remove(dst + ".part")
        raise ValueError("SHA-256 does not match the release notes")
    os.replace(dst + ".part", dst)
    return dst
