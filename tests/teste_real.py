"""Real-data check (manual, not part of CI): copies a sample of a real library, runs everything, undoes, compares.

Uso: python tests/teste_real.py D:\\musica D:\\groovewizard-teste [N]
Never touches the source library: it only reads it to copy N tracks.
Checks: no audio lost, audio data byte-identical (tags excluded), Undo restores paths and tags.
"""
import hashlib
import os
import random
import shutil
import struct
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = os.path.join(sys.argv[2] + "_appdata")  # caches/logs of the test kept apart

import organizador.pipeline as pl  # noqa: E402
from organizador.tags import AUDIO, raw_genre  # noqa: E402


def audio_hash(path):
    """md5 of the audio data only (tags/metadata excluded), so tag edits don't count as changes."""
    ext = os.path.splitext(path)[1].lower()
    data = open(path, "rb").read()
    if ext == ".mp3":
        start = 0
        if data[:3] == b"ID3":
            sz = data[6:10]
            start = 10 + ((sz[0] << 21) | (sz[1] << 14) | (sz[2] << 7) | sz[3]) + (10 if data[5] & 0x10 else 0)
        end = len(data) - (128 if data[-128:-125] == b"TAG" else 0)
        body = data[start:end]
        if body[-32:-24] == b"APETAGEX":  # APE footer
            body = body[: -(struct.unpack("<I", body[-20:-16])[0] + 32)]
        return hashlib.md5(body).hexdigest()
    if ext == ".flac":
        i = 4
        while True:
            last, size = data[i] & 0x80, int.from_bytes(data[i + 1:i + 4], "big")
            i += 4 + size
            if last:
                break
        return hashlib.md5(data[i:]).hexdigest()
    if ext in (".wav", ".aiff", ".aif"):
        want, big = (b"data", False) if ext == ".wav" else (b"SSND", True)
        i = 12
        while i + 8 <= len(data):
            cid, size = data[i:i + 4], struct.unpack(">I" if big else "<I", data[i + 4:i + 8])[0]
            if cid == want:
                return hashlib.md5(data[i + 8:i + 8 + size]).hexdigest()
            i += 8 + size + (size & 1)
    if ext == ".m4a":
        i = 0
        while i + 8 <= len(data):
            size, typ = struct.unpack(">I4s", data[i:i + 8])
            if size == 1:
                size = struct.unpack(">Q", data[i + 8:i + 16])[0]
            if typ == b"mdat":
                return hashlib.md5(data[i:i + size]).hexdigest()
            if size < 8:
                break
            i += size
    return hashlib.md5(data).hexdigest()


def state(root):
    out = {}
    for dp, _, fs in os.walk(root):
        for n in fs:
            if os.path.splitext(n)[1].lower() in AUDIO:
                p = os.path.join(dp, n)
                out[os.path.relpath(p, root)] = (audio_hash(p), raw_genre(p))
    return out


def main():
    src, dst = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    if os.path.exists(dst):
        sys.exit(f"{dst} ja existe: apaga-o ou escolhe outro")
    files = [os.path.join(dp, f) for dp, ds, fs in os.walk(src) if "\\_" not in dp and "downloading" not in dp.lower()
             for f in fs if os.path.splitext(f)[1].lower() in AUDIO]
    random.seed(7)
    sample = random.sample(files, min(n, len(files)))
    loose, packed = sample[: int(len(sample) * 0.8)], sample[int(len(sample) * 0.8):]
    os.makedirs(os.path.join(dst, "novas"))
    for p in loose:
        shutil.copy2(p, os.path.join(dst, "novas", os.path.basename(p)))
    for p in loose[:10]:  # a duplicate of 10 of them, as a shorter-named radio edit copy
        b, e = os.path.splitext(os.path.basename(p))
        shutil.copy2(p, os.path.join(dst, "novas", f"{b} (Radio Edit){e}"))
    with zipfile.ZipFile(os.path.join(dst, "Best New Tech House Pack.zip"), "w") as z:
        for p in packed:
            z.write(p, os.path.basename(p))
        z.writestr("cover.jpg", b"x")
    before = state(dst)
    print(f"amostra: {len(before)} faixas soltas + {len(packed)} num zip")

    t0 = time.time()
    opts = pl.Options(root=dst, online=False)  # online needs keys; tested separately
    rep, errs = pl.Organizer(opts).run()
    print(f"organizar: {time.time() - t0:.0f} s", dict(rep), "erros:", errs[:5])
    after = state(dst)
    q = state(os.path.join(dst, pl.QUARANTINE)) if os.path.isdir(os.path.join(dst, pl.QUARANTINE)) else {}
    lib = {k: v for k, v in after.items() if not k.startswith(pl.QUARANTINE)}
    hashes_before = sorted(h for h, _ in before.values())
    zip_hashes = sorted(audio_hash(p) for p in packed)
    hashes_after = sorted([h for h, _ in lib.values()] + [h for h, _ in q.values()])
    assert hashes_after == sorted(hashes_before + zip_hashes), "faixas perdidas ou audio alterado!"
    print(f"ok: nenhuma faixa perdida, audio identico ({len(lib)} na biblioteca, {len(q)} em quarentena)")
    no_genre = sum(1 for k in lib if k.startswith(pl.FOLDER_NAMES["pt"][pl.NO_GENRE]))
    print(f"   sem genero: {no_genre}; generos: {sorted({k.split(os.sep)[0] for k in lib})}")

    t0 = time.time()
    rep, errs = pl.undo_last(dst)
    print(f"desfazer: {time.time() - t0:.0f} s", dict(rep), "erros:", errs[:5])
    # the extracted copies are put aside in quarantine (the zip itself stays), so compare the rest
    back = {k: v for k, v in state(dst).items() if not k.startswith((pl.INBOX, pl.QUARANTINE))}
    assert {k: v for k, v in back.items()} == before, "desfazer nao repos tudo igual"
    print("ok: desfazer repos caminhos, audio e generos exatamente como antes")


if __name__ == "__main__":
    main()
