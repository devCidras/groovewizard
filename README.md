<p align="center"><img src="organizador/recursos/groovewizard.png" width="128" alt="GrooveWizard"></p>

<h1 align="center">GrooveWizard</h1>

<p align="center">
  Arruma a tua biblioteca de música de DJ: por género e subgénero, sem repetidas, com as tags limpas.<br>
  <a href="../../releases/latest"><b>Descarregar o instalador</b></a> · Windows 10/11 · Português / English · <a href="#english">English below</a>
</p>

<p align="center">
  <a href="../../actions/workflows/testes.yml"><img src="../../actions/workflows/testes.yml/badge.svg" alt="testes"></a>
</p>

<p align="center"><sub>Até à versão 1.1.0 chamava-se <i>Cratekeeper</i>; a atualização mantém definições, chaves e histórico. ·
Called <i>Cratekeeper</i> up to 1.1.0; updating keeps settings, keys and history.</sub></p>

<p align="center"><img src="docs/1-principal.png" width="860" alt="Janela do GrooveWizard"></p>

> ⚠️ **Faz uma cópia de segurança antes da primeira utilização.** O GrooveWizard move ficheiros e altera tags. Tem
> pré-visualização, desfazer e quarentena, mas são proteções, não substituem uma cópia de segurança.

## O que faz

1. **Descompacta os packs** que descarregaste (`.zip`, `.rar`, `.7z`, mesmo packs dentro de packs). Para `.rar` e `.7z` é preciso o [7-Zip](https://7-zip.org).
2. **Arruma por género**: cada faixa vai para a pasta do seu género (ex.: `House/Tech House`). Se a faixa não disser o género, usa o nome do pack (ex.: "Best New Hard Techno" → `Techno/Hard Techno`). Se não houver nada, vai para `Sem Genero`.
3. **Tira as repetidas**: se tens a mesma faixa duas vezes, fica a melhor (a Extended, senão a mais longa, senão a de melhor qualidade). A outra vai para a quarentena durante 30 dias. Remixes diferentes não contam como repetidas.
4. **Procura o género online** das faixas que não o têm (Discogs, Last.fm e, se quiseres, MusicBrainz). É uma estimativa, não uma garantia.
5. **Separa por BPM** as faixas sem género (`BPM 122-128`, `BPM 128-135`, …).
6. **Limpa as tags**: grava o género dentro da faixa (o rekordbox / Serato passam a mostrá-lo) e tira nomes de sites como `www.djsoundtop.com` do título, álbum e comentários.
7. **Limpa os nomes das faixas novas**: tira o site do nome do ficheiro e, se quiseres, dá o nome `Artista - Título (Extended Mix)`. As faixas dos packs mudam logo; outras faixas novas só depois de confirmares. As que já tinhas não mudam de nome (o rekordbox deixaria de as encontrar), a não ser que ligues a opção para as faixas antigas, que pergunta antes.
8. **Agrupa géneros parecidos**: `House/Tech House`, `Techno/Hard Techno`, `Melodic & Indie/…`, `Bass & Breaks/…`, `Dance & Mainstage/…`.
9. **Pastas protegidas**: escolhes pastas em que a app nunca toca (os teus edits, sets já preparados).
10. **Só faixas novas** (opção): mais rápido, arruma só o que chegou desde a última vez. As faixas que já tinhas não são tocadas.
11. **Relatório**: mostra, sem mexer em nada, as faixas sem artista ou título, sem género, MP3 de menor qualidade, muito curtas ou com tags estragadas (lista para o Excel).

**Formatos de áudio:** MP3, FLAC, AIFF/AIF, WAV e M4A.

## Capturas

| A organizar | No fim |
|---|---|
| <img src="docs/2-a-organizar.png" alt="A organizar, com o progresso de cada passo"> | <img src="docs/3-resumo.png" alt="Resumo no fim da organização"> |
| **Ver lista: o que vai mudar, faixa a faixa** | **Desfazer: voltar a uma organização anterior** |
| <img src="docs/8-lista.png" alt="Lista do que vai mudar, com faixas desmarcadas"> | <img src="docs/9-desfazer.png" alt="Lista de organizações para desfazer"> |
| **Ajuda dentro da app** | **Termos na primeira utilização (EN)** |
| <img src="docs/4-ajuda.png" alt="Ajuda"> | <img src="docs/5-termos-en.png" alt="Termos e Condições em inglês"> |
| **Aviso de versão nova** | **Interface em inglês** |
| <img src="docs/6-atualizacao.png" alt="Barra de atualização"> | <img src="docs/7-english.png" alt="Interface em inglês"> |

## Proteções

- **Pré-visualizar** mostra o que vai mudar, sem mexer em nada. **Ver lista** mostra-o faixa a faixa e deixa-te desmarcar as faixas em que não queres mexer. (Não consegue prever as faixas ainda dentro dos packs nem os resultados da procura online.)
- **Desfazer…** mostra as últimas organizações e volta atrás até à que escolheres: as faixas regressam ao sítio, as repetidas saem da quarentena e as tags voltam ao que eram. O que não conseguir repor (apagado ou mudado à mão entretanto) aparece numa lista.
- **Quarentena**: as repetidas vão para uma pasta escondida (`_quarentena`) dentro da biblioteca. Ficam lá 30 dias e depois vão para a Reciclagem (ou já, com **Esvaziar quarentena**).
- As tags são gravadas primeiro numa cópia, que é verificada antes de substituir a faixa. Ficheiros estragados (que não se conseguem ler) não são mexidos. No fim, as pastas que ficaram vazias são apagadas.
- Recusa pastas perigosas (disco inteiro, pasta do utilizador, Windows, Program Files, AppData) e não deixa duas janelas organizar a mesma biblioteca.

## Como usar

1. Descarrega `GrooveWizard-<versão>-setup.exe` em [Releases](../../releases/latest) e confirma o ficheiro (ver [Verificar o download](#verificar-o-download)). O instalador não tem assinatura digital, por isso o Windows SmartScreen pode avisar.
2. Na primeira vez escolhe o idioma e aceita os termos.
3. Escolhe a pasta das músicas.
4. (Recomendado) cola as chaves grátis e carrega em **Verificar**:
   - Discogs: <https://www.discogs.com/settings/developers> → *Generate new token*
   - Last.fm: <https://www.last.fm/api/account/create> (só precisas da *API key*)
5. **Fecha o rekordbox/Serato**, carrega em **Pré-visualizar** e depois em **Organizar**. Para deixar a correr de noite, liga **Desligar PC no fim**: se a organização terminar sem erros, o PC desliga-se (com 60 s para cancelar). Se houver um erro ou cancelares, fica ligado.
6. No rekordbox: *Ficheiro → Gerir faixas inexistentes → Auto Relocate* (escolhe a pasta), depois *Recarregar tag*.

Ajuda completa dentro da app (botão **Ajuda** ou F1).

## Requisitos e limites

- Windows 10 ou 11. O instalador já inclui o Python; não é preciso instalar nada além do 7-Zip (só para `.rar`/`.7z`).
- Espaço livre: o que os packs ocupam depois de descompactados, mais 1 GB de margem.
- Internet só é precisa para a procura online e para o aviso de versão nova.
- **Não mexe nas bases de dados do rekordbox ou do Serato** (playlists, cues, beat grids): só move ficheiros e altera tags. Depois de organizar, é preciso voltar a localizar os ficheiros no programa de DJ. O fluxo está documentado para o rekordbox; no Serato não foi testado.
- A deteção de repetidas e a procura online são estimativas: revê a pré-visualização e, se tiveres dúvidas, a pasta `_quarentena` antes de a esvaziar.
- No instalador, o BPM vem só da tag; faixas sem BPM na tag vão para `BPM desconhecido`.
- Cancelar a meio deixa feito o que já foi feito (e pode ser desfeito).
- Na primeira organização com a versão 1.5.0 a app lê um pedaço de cada faixa para a reconhecer depois (16 mil faixas num disco rígido: uns 5 minutos, uma só vez).
- Desinstalar não apaga as definições em `%APPDATA%\GrooveWizard`.

## Perguntas frequentes

**Depois de organizar, o rekordbox mostra faixas com "!".** É normal: os ficheiros mudaram de pasta. *Gerir faixas inexistentes → Auto Relocate*.

**Os `.rar` não descompactam.** Instala o [7-Zip](https://7-zip.org).

**Ficaram muitas faixas em `Sem Genero`.** Confirma as chaves (botão **Verificar**) e liga o MusicBrainz nas opções (mais lento).

**Uma faixa foi para a quarentena e não devia.** Usa **Desfazer…**, ou copia-a de `_quarentena` de volta (a pasta está escondida: no Explorador, *Ver → Mostrar → Itens ocultos*).

**O Menu Iniciar mostra o ícone antigo depois de atualizar.** É a cache de ícones do Windows; reinicia o PC.

## Privacidade

- As chaves ficam em `%APPDATA%\GrooveWizard\config.json`, encriptadas com o Windows (DPAPI) sempre que o Windows o permite; só o teu utilizador neste PC as consegue ler. São enviadas apenas ao próprio serviço (Discogs ou Last.fm), na procura online e quando carregas em **Verificar**.
- Na procura online, o Discogs recebe o artista e o título; o Last.fm e o MusicBrainz recebem o artista.
- Ao abrir, a app pergunta ao GitHub se há uma versão nova. Como em qualquer pedido na internet, o GitHub vê o teu IP. Isto acontece sempre, para avisar de cada versão nova.
- Caches (artistas e títulos pesquisados), registos e o histórico para desfazer ficam em `%APPDATA%\GrooveWizard\bibliotecas\`, **fora** da pasta das músicas, para não aparecerem se a partilhares no Soulseek/Nicotine+. Se a app falhar, o erro fica em `%APPDATA%\GrooveWizard\erros.log`.
- Nada é enviado aos autores.

## Verificar o download

Cada release indica o SHA-256 do instalador. No PowerShell:

```powershell
Get-FileHash .\GrooveWizard-<versão>-setup.exe -Algorithm SHA256
```

O valor tem de ser igual ao das notas da release. O botão **Atualizar** da app faz esta verificação sozinho e não abre um instalador que não bata certo.

O SHA-256 confirma que o ficheiro chegou inteiro e é o mesmo que foi publicado; não prova quem o publicou (o instalador não tem assinatura digital). Descarrega só da página de releases deste repositório.

## Para programadores

```bash
pip install -r requirements.txt
python app.py
```

- Testes: `python tests/test_pipeline.py` (também correm no GitHub a cada push, com build e arranque do `.exe`).
- Teste com dados reais (só lê a biblioteca, trabalha numa cópia): `python tests/teste_real.py D:\Musica D:\groovewizard-teste 150`
- Medir o BPM no áudio das faixas sem BPM na tag: `pip install librosa` (opcional; não vai no instalador).
- Gerar o `.exe` e o instalador: `powershell -File build.ps1` → `dist\GrooveWizard\` e `dist\GrooveWizard-<versão>-setup.exe` (precisa do [Inno Setup 6](https://jrsoftware.org/isinfo.php)).
- Géneros, sinónimos de tags ("Afro House" → House), regras pelo nome dos packs e pastas-mãe: [`organizador/regras.py`](organizador/regras.py). Textos da interface (PT/EN): [`organizador/i18n.py`](organizador/i18n.py).
- Problemas e sugestões: abre uma [issue](../../issues). Problemas de segurança: reporta em privado em [Security → Report a vulnerability](../../security/advisories/new), não numa issue pública.

---

<h2 id="english">English</h2>

**GrooveWizard** tidies a DJ music library on Windows 10/11. Interface in English and Portuguese.

> ⚠️ **Back up your music before the first run.** GrooveWizard moves files and edits tags. Preview, Undo and the
> quarantine are safeguards, not a backup.

**What it does:**
- Unpacks the packs you download (zip/rar/7z, packs inside packs too; rar/7z need [7-Zip](https://7-zip.org)).
- Puts each track in the folder of its genre (from the track's genre, else from the pack name).
- Removes duplicates: the best copy stays (the Extended, else the longest); the other goes to quarantine for 30 days.
- Looks up missing genres online (Discogs, Last.fm, optionally MusicBrainz) — an estimate, not a guarantee.
- Splits tracks without a genre by BPM and saves the genre inside each track.
- Removes website names (e.g. `www.djsoundtop.com`) from tags and from new tracks' file names; can name new tracks `Artist - Title (Extended Mix)`. Tracks from packs change right away, other new tracks after you confirm; tracks you already had keep their name unless you turn on the option for old tracks (it asks first).
- Protected folders are never touched; *Only new tracks* sorts only what arrived since last time; *Report* lists tracks with problems without changing anything.
- Formats: MP3, FLAC, AIFF/AIF, WAV, M4A.

**Safeguards:** *Preview* changes nothing and *See list* shows every change track by track, so you can untick tracks. *Undo…* goes back to any recent organize: tracks return to where they were, duplicates come out of quarantine and tags go back to what they were. Removed tracks wait 30 days in a hidden `_quarentena` folder before going to the Recycle Bin. Tags are written to a checked copy first. Dangerous folders (whole drive, user folder, Windows) are refused.

**Use:** download the installer from [Releases](../../releases/latest) and [verify it](#verificar-o-download) (unsigned: SmartScreen may warn). Choose your music folder, paste free Discogs/Last.fm keys and press **Check**, close rekordbox/Serato, **Preview**, then **Organize**. Optionally turn on *Shut down when done*: the PC shuts down (60 s to cancel) only if the run finishes without errors. In rekordbox: *File → Manage Missing Files → Auto Relocate*, then *Reload Tag*.

**Limits:** it does not touch rekordbox/Serato databases (playlists, cues, beat grids) — relocate files afterwards (documented for rekordbox; untested on Serato). Duplicate detection and online genres are heuristics: review the preview and the quarantine. The installer reads BPM from tags only. Uninstalling keeps `%APPDATA%\GrooveWizard`.

**Privacy:** API keys are DPAPI-encrypted when Windows allows it and are sent only to their own service. Discogs receives artist and title; Last.fm and MusicBrainz receive the artist. At start-up the app asks GitHub for the latest version (GitHub sees your IP; always on, so every new version is announced). Caches, logs and undo history live in `%APPDATA%\GrooveWizard`, outside the music folder; crashes are written to `%APPDATA%\GrooveWizard\erros.log`. The SHA-256 in each release proves integrity (the file is the one published), not authorship: the installer is unsigned, so download only from this repository's Releases. Nothing is sent to the authors.

**From source:** `pip install -r requirements.txt && python app.py`. Tests: `python tests/test_pipeline.py`. Bugs and ideas: open an [issue](../../issues). Security problems: report privately via [Security → Report a vulnerability](../../security/advisories/new), not in a public issue.

## Licença / License

[GPL-3.0-or-later](LICENSE). O instalador inclui componentes de terceiros com as suas licenças (mutagen GPL-2.0-or-later, Qt/PySide6 LGPL-3.0, Send2Trash BSD, Python PSF): ver [`licencas/AVISOS_TERCEIROS.md`](licencas/AVISOS_TERCEIROS.md), que inclui a oferta de código-fonte. / The installer bundles third-party components under their own licenses; see the notices file, which includes the written source offer.

rekordbox, Serato, Beatport, Discogs, Last.fm e MusicBrainz são marcas dos respetivos donos; o GrooveWizard não está associado a nenhum deles.
