# Cratekeeper

App para Windows que arruma uma biblioteca de música de DJ: extrai os packs descarregados, separa as faixas por género (e subgénero), remove repetidas ficando com a Extended Mix, procura online o género das que não o têm e limpa as tags (sites de download no Álbum, listas de géneros, etc.).

*English below.*

## O que faz

1. **Extrai** `.zip`, `.rar` e `.7z` (para `.rar`/`.7z` precisa do [7-Zip](https://7-zip.org)).
2. **Arruma por género** pela tag Genre. Se a faixa não tem tag, usa o nome do pack (ex.: "Best New Hard Techno" → Hard Techno).
3. **Remove repetidas**: mesma faixa = mesmos artistas + mesmo título (ignora "Original Mix", "feat.", ordem dos artistas). Fica a **Extended**, senão a mais longa, senão a lossless. As outras vão para a **Reciclagem**.
4. **Procura online** o género das que ficaram em `Sem Genero`: Discogs (estilo da própria faixa), Last.fm e, opcionalmente, MusicBrainz.
5. **Separa por BPM** as pastas `Sem Genero` e `Outros` (`BPM 122-128`, `BPM 128-135`, ...).
6. **Corrige as tags**: grava o género da pasta na tag Genre (o rekordbox/Serato passam a mostrar o género certo) e tira nomes de sites do Álbum, Título, Comentário, etc.
7. **Agrupa em pastas-mãe**: `House/Tech House`, `Techno/Hard Techno`, `Melodic & Indie/...`, ...

Tudo o que é movido fica registado: o botão **Desfazer última** devolve os ficheiros. Nada é apagado de vez — o que sai vai para a Reciclagem.

## Como usar

1. Descarrega o `.exe` em [Releases](../../releases) (ou corre do código, ver abaixo).
2. Escolhe a pasta das músicas.
3. (Opcional, recomendado) cola as chaves grátis:
   - Discogs: <https://www.discogs.com/settings/developers> → *Generate new token*
   - Last.fm: <https://www.last.fm/api/account/create>
4. **Pré-visualizar** mostra o que vai mudar sem mexer em nada. **Organizar** faz.
5. No rekordbox: *Ficheiro → Gerir faixas inexistentes → Auto Relocate* (escolhe a pasta), depois *Recarregar tag*.

Fecha o rekordbox/Serato enquanto organizas.

As chaves e as definições ficam em `%APPDATA%\Cratekeeper\config.json`, só no teu PC. Caches e registos ficam em `%APPDATA%\Cratekeeper\bibliotecas\` — **fora** da pasta das músicas, para não aparecerem se a partilhares no Soulseek/Nicotine+.

## Correr do código

```bash
pip install -r requirements.txt
python app.py
```

Testes: `python tests/test_pipeline.py`

Para medir o BPM das faixas que não o têm na tag: `pip install librosa` (opcional).

Gerar o `.exe`: `powershell -File build.ps1` → `dist\Cratekeeper.exe`.

## Personalizar géneros

Os nomes das pastas, os sinónimos de tags ("Afro House" → House, "Hardtechno" → Hard Techno), as regras pelos nomes dos packs e as pastas-mãe estão em [`organizador/regras.py`](organizador/regras.py).

---

## English

Windows app that tidies a DJ music library: extracts downloaded packs, sorts tracks into genre/subgenre folders, removes duplicates keeping the Extended Mix, looks up missing genres online (Discogs, Last.fm, MusicBrainz), splits untagged tracks by BPM and cleans tags (download-site names in Album, genre lists). Every move can be undone; removed files go to the Recycle Bin. Genre rules live in `organizador/regras.py`. Run with `pip install -r requirements.txt && python app.py`.

## Licença / License

MIT
