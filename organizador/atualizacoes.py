"""Update check: asks GitHub for the latest release and, on request, downloads its installer.

Only one request to api.github.com at start-up (no personal data). Silent on any failure: no internet, private
repo (404), rate limit... the app simply works without telling anyone.
"""
import hashlib
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request

from . import __version__

REPO = "devCidras/groovewizard"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
UA = f"GrooveWizard/{__version__}"
MAX_DOWNLOAD = 300 * 1024 * 1024
DOWNLOAD_HOSTS = {
    "github.com", "objects.githubusercontent.com",
    "github-releases.githubusercontent.com", "release-assets.githubusercontent.com",
}


def parse(v):
    """'v1.0.10' -> (1, 0, 10); anything odd -> ()."""
    n = [int(x) for x in re.findall(r"\d+", v or "")[:3]]
    return tuple(n + [0] * (3 - len(n))) if n else ()  # '1.0' == '1.0.0'


def newer(remote, local=__version__):
    return bool(parse(remote)) and parse(remote) > parse(local)


def check(timeout=6):
    """-> {"version", "page", "installer", "notes"} when a newer release exists, else None."""
    try:
        req = urllib.request.Request(API, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            rel = json.load(r)
        if not isinstance(rel, dict) or rel.get("draft") or rel.get("prerelease"):
            return None
        tag, body, assets = rel.get("tag_name", ""), rel.get("body", ""), rel.get("assets", [])
        if not isinstance(tag, str) or not isinstance(body, str) or not isinstance(assets, list) or not newer(tag):
            return None
        setup = next((a for a in assets if isinstance(a, dict) and isinstance(a.get("name"), str)
                      and re.search(r"setup\.exe$", a["name"], re.I)), None)
        sha = re.search(r"SHA-256:\s*`?([0-9a-fA-F]{64})", body)
        page = rel.get("html_url") if isinstance(rel.get("html_url"), str) else f"https://github.com/{REPO}/releases"
        installer = setup.get("browser_download_url") if setup and isinstance(setup.get("browser_download_url"), str) else None
        return {"version": tag.lstrip("v"), "page": page,
                "installer": installer, "sha256": sha and sha.group(1).lower(),
                "notes": body}
    except Exception:
        return None


def download(url, sha256, progress=None):
    """Installer -> %TEMP%, only from github.com, and only kept if its SHA-256 matches the one in the release notes
    (the app never runs an installer it could not verify)."""
    if not re.match(r"^https://(github\.com|objects\.githubusercontent\.com)/", url or ""):
        raise ValueError("unexpected download address")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        raise ValueError("release has no SHA-256 to check against")
    name = os.path.basename(urllib.parse.urlsplit(url).path)
    if not name:
        raise ValueError("download has no file name")
    dst = os.path.join(tempfile.gettempdir(), name)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(dst + ".part", "wb") as fh:
            total = int(r.headers.get("Content-Length") or 0)
            final_host = (urllib.parse.urlsplit(getattr(r, "geturl", lambda: url)()).hostname or "").lower()
            if final_host not in DOWNLOAD_HOSTS:
                raise ValueError("unexpected redirected download address")
            if total > MAX_DOWNLOAD:
                raise ValueError("installer is too large")
            done = 0
            h = hashlib.sha256()
            while chunk := r.read(1 << 16):
                fh.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if done > MAX_DOWNLOAD:
                    raise ValueError("installer is too large")
                if progress:
                    progress(done, total)
    except BaseException:
        if os.path.exists(dst + ".part"):
            os.remove(dst + ".part")  # half a download is never left in %TEMP%
        raise
    if h.hexdigest() != sha256:
        os.remove(dst + ".part")
        raise ValueError("SHA-256 does not match the release notes")
    os.replace(dst + ".part", dst)
    return dst
