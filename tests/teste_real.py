"""Real-data check (manual, not part of CI): copies a sample of a real library, runs everything, undoes, compares.

Uso: python tests/teste_real.py D:\\musica D:\\groovewizard-teste [N]
Never touches the source library: it only reads it to copy N tracks.
Checks: no audio lost, audio data byte-identical (tags excluded), Undo restores paths and tags.
"""
import argparse
import hashlib
import os
import random
import shutil
import struct
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from organizador.tags import AUDIO, picture_records, snapshot  # noqa: E402


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
        while i + 4 <= len(data):
            last, size = data[i] & 0x80, int.from_bytes(data[i + 1:i + 4], "big")
            i += 4 + size
            if last:
                if i < len(data):
                    return hashlib.md5(data[i:]).hexdigest()
                break
        raise ValueError(f"FLAC truncado: {path}")
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
        digest = hashlib.md5()
        audio_size = 0
        while i + 8 <= len(data):
            size, typ = struct.unpack(">I4s", data[i:i + 8])
            header = 8
            if size == 1:
                if i + 16 > len(data):
                    break
                size = struct.unpack_from(">Q", data, i + 8)[0]
                header = 16
            elif size == 0:
                size = len(data) - i
            if size < header or i + size > len(data):
                raise ValueError(f"M4A inválido: {path}")
            if typ == b"mdat":
                digest.update(memoryview(data)[i + header:i + size])
                audio_size += size - header
            i += size
        if i != len(data) or not audio_size:
            raise ValueError(f"Não foi possível verificar o áudio M4A: {path}")
        return digest.hexdigest()
    return hashlib.md5(data).hexdigest()


def state(root):
    out = {}
    for dp, _, fs in os.walk(root):
        for n in fs:
            if os.path.splitext(n)[1].lower() in AUDIO:
                p = os.path.join(dp, n)
                out[os.path.relpath(p, root)] = (audio_hash(p), snapshot(p), picture_records(p))
    return out


def main():
    parser = argparse.ArgumentParser(description="Verifica Organizar e Desfazer numa cópia da biblioteca.")
    parser.add_argument("origem", type=Path)
    parser.add_argument("destino", type=Path)
    parser.add_argument("quantidade", type=int, nargs="?", default=200)
    args = parser.parse_args()
    src, dst = args.origem.resolve(), args.destino.resolve()
    profile = dst.with_name(dst.name + "_appdata") if dst.name else dst
    if not src.is_dir() or args.quantidade <= 0:
        parser.error("Indica uma pasta de origem existente e uma quantidade positiva.")
    if dst.is_relative_to(src) or profile.is_relative_to(src) or dst.exists() or profile.exists():
        parser.error("Escolhe um destino novo fora da biblioteca, com espaço para a cópia e o perfil de teste.")
    files = []
    for dp, dirs, names in os.walk(src):
        dirs[:] = sorted(d for d in dirs if not d.startswith("_") and "downloading" not in d.lower())
        files.extend(Path(dp, name) for name in sorted(names) if Path(name).suffix.lower() in AUDIO)
    if not files:
        parser.error("Não encontrei faixas compatíveis na pasta de origem.")
    sample = random.Random(7).sample(files, min(args.quantidade, len(files)))
    loose, packed = sample[: int(len(sample) * 0.8)], sample[int(len(sample) * 0.8):]
    dst.mkdir(parents=True)
    profile.mkdir()
    os.environ["APPDATA"] = str(profile)
    import organizador.pipeline as pl  # uses the isolated profile at import

    for p in loose:
        target = dst / "novas" / p.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
    for p in loose[:10]:
        target = dst / "duplicadas" / p.relative_to(src).with_name(f"{p.stem} (Radio Edit){p.suffix}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
    with zipfile.ZipFile(os.path.join(dst, "Best New Tech House Pack.zip"), "w") as z:
        for p in packed:
            z.write(p, p.relative_to(src))
        z.writestr("cover.jpg", b"x")
    before = state(dst)
    print(f"amostra: {len(before)} faixas soltas + {len(packed)} num zip")

    t0 = time.time()
    opts = pl.Options(root=dst, online=False, rename_packs=True)  # online needs keys; tested separately
    rep, errs = pl.Organizer(opts).run()
    organize_errors = errs
    print(f"organizar: {time.time() - t0:.0f} s", dict(rep), "erros:", errs[:5])
    after = state(dst)
    q = state(os.path.join(dst, pl.QUARANTINE)) if os.path.isdir(os.path.join(dst, pl.QUARANTINE)) else {}
    lib = {k: v for k, v in after.items() if not k.startswith(pl.QUARANTINE)}
    hashes_before = sorted(v[0] for v in before.values())
    zip_hashes = sorted(audio_hash(p) for p in packed)
    hashes_after = sorted([v[0] for v in lib.values()] + [v[0] for v in q.values()])
    if hashes_after != sorted(hashes_before + zip_hashes):
        sys.exit("O áudio organizado difere da amostra original.")
    print(f"ok: nenhuma faixa perdida, audio identico ({len(lib)} na biblioteca, {len(q)} em quarentena)")
    no_genre = sum(1 for k in lib if k.startswith(pl.FOLDER_NAMES["pt"][pl.NO_GENRE]))
    print(f"   sem genero: {no_genre}; generos: {sorted({k.split(os.sep)[0] for k in lib})}")

    t0 = time.time()
    rep, errs = pl.undo_last(dst)
    print(f"desfazer: {time.time() - t0:.0f} s", dict(rep), "erros:", errs[:5])
    # the extracted copies are put aside in quarantine (the zip itself stays), so compare the rest
    back = {k: v for k, v in state(dst).items() if not k.startswith((pl.INBOX, pl.QUARANTINE))}
    if back != before:
        sys.exit("Desfazer não repôs todos os caminhos, conteúdos de áudio, tags e capas.")
    if organize_errors or errs:
        sys.exit("O teste registou erros ao organizar ou desfazer. Consulta as mensagens acima.")
    print("ok: desfazer repos caminhos, audio, tags, versao ID3 e metadados das capas exatamente como antes")


if __name__ == "__main__":
    main()
