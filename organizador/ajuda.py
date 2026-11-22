"""Help, About and Terms dialogs (Portuguese / English)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QTextBrowser,
                               QVBoxLayout)

from . import __version__, termos
from .i18n import LANGS, lang, set_lang, t
from .theme import C

AUTHOR = "devCidras"
REPO = "https://github.com/devCidras/organizador-musica"

_CSS = f"""
<style>
  body {{ color: {C['fg']}; font-size: 14px; line-height: 150%; }}
  h2 {{ font-size: 18px; margin: 0 0 6px 0; }}
  h3 {{ font-size: 15px; margin: 18px 0 4px 0; color: {C['fg']}; }}
  p, li {{ color: #CBD5E1; }}
  .muted {{ color: {C['fg_muted']}; }}
  a {{ color: {C['accent']}; }}
  code {{ background: {C['muted']}; }}
</style>
"""

HELP = {
    "pt": """
<h2>Como usar</h2>
<ol>
  <li><b>Fecha o rekordbox / Serato.</b> A app move ficheiros e eles não podem estar abertos.</li>
  <li><b>Biblioteca:</b> escolhe a pasta onde tens as músicas (ex.: <code>D:\\musica</code>).
      Os packs <code>.zip</code>/<code>.rar</code> descarregados podem ficar lá dentro.</li>
  <li><b>Fontes online</b> (opcional, recomendado): cola as chaves grátis do Discogs e do Last.fm.
      Servem para descobrir o género das faixas que não o têm.</li>
  <li><b>Passos:</b> liga ou desliga o que queres que a app faça.</li>
  <li><b>Pré-visualizar</b> mostra o que ia mudar, <b>sem mexer em nada</b>.</li>
  <li><b>Organizar</b> faz as mudanças. Podes <b>Cancelar</b> a meio: o que já foi feito fica feito.</li>
  <li>No fim, no <b>rekordbox</b>: <i>Ficheiro › Gerir faixas inexistentes › Auto Relocate</i> (escolhe a pasta)
      e depois, na Coleção, <i>Ctrl+A › botão direito › Recarregar tag</i>.</li>
</ol>
<h3>Criar as chaves (grátis, 2 minutos)</h3>
<p><b>Discogs:</b> entra em <a href="https://www.discogs.com/settings/developers">discogs.com/settings/developers</a>
   e carrega em <i>Generate new token</i>.<br>
   <b>Last.fm:</b> em <a href="https://www.last.fm/api/account/create">last.fm/api/account/create</a> preenche
   nome e descrição; copia a <i>API key</i> (não precisas do <i>shared secret</i>).</p>
<h3>O que acontece às faixas</h3>
<ul>
  <li><b>Géneros:</b> cada faixa vai para a pasta do seu género (ex.: <code>House\\Tech House</code>).
      Sem tag, usa o nome do pack; sem nada, fica em <code>Sem Genero</code>.</li>
  <li><b>Repetidas:</b> fica a <b>Extended Mix</b>; se não houver, a mais longa; depois a lossless.
      As outras vão para a <b>Reciclagem</b> do Windows.</li>
  <li><b>Outros:</b> géneros com poucas faixas (Pop, Hardstyle, Rock…). O género verdadeiro fica na tag.</li>
  <li><b>BPM:</b> <code>Sem Genero</code> e <code>Outros</code> ficam divididos em pastas de BPM.</li>
  <li><b>Tags:</b> o género da pasta é gravado na tag Genre; nomes de sites de download saem do Álbum, Título, etc.</li>
</ul>
<h3>Enganei-me, e agora?</h3>
<p><b>Desfazer última</b> devolve os ficheiros que foram movidos na última execução.
   O que foi para a Reciclagem restauras pelo Windows (Reciclagem › Restaurar).</p>
<h3>Onde ficam os dados</h3>
<p class="muted">Definições e chaves: <code>%APPDATA%\\OrganizadorMusica\\config.json</code> (só neste PC).<br>
   Caches e registos: <code>%APPDATA%\\OrganizadorMusica\\bibliotecas</code> — fora da pasta das músicas,
   para não aparecerem se a partilhares no Soulseek / Nicotine+.</p>
<h3>Problemas comuns</h3>
<ul>
  <li><b>.rar não extrai:</b> instala o <a href="https://7-zip.org">7-Zip</a>.</li>
  <li><b>Muitas faixas em "Sem Genero":</b> confirma as chaves; liga o MusicBrainz (mais lento).</li>
  <li><b>Faixas com "!" no rekordbox:</b> é normal depois de organizar — faz o Auto Relocate.</li>
</ul>
""",
    "en": """
<h2>How to use</h2>
<ol>
  <li><b>Close rekordbox / Serato.</b> The app moves files and they must not be open.</li>
  <li><b>Library:</b> choose the folder with your music (e.g. <code>D:\\Music</code>).
      Downloaded <code>.zip</code>/<code>.rar</code> packs can stay inside it.</li>
  <li><b>Online sources</b> (optional, recommended): paste your free Discogs and Last.fm keys.
      They are used to find the genre of tracks that have none.</li>
  <li><b>Steps:</b> turn on or off what you want the app to do.</li>
  <li><b>Preview</b> shows what would change, <b>without touching anything</b>.</li>
  <li><b>Organize</b> makes the changes. You can <b>Cancel</b> halfway: what's done stays done.</li>
  <li>Afterwards, in <b>rekordbox</b>: <i>File › Manage Missing Files › Auto Relocate</i> (pick the folder),
      then in the Collection <i>Ctrl+A › right-click › Reload Tag</i>.</li>
</ol>
<h3>Getting the keys (free, 2 minutes)</h3>
<p><b>Discogs:</b> go to <a href="https://www.discogs.com/settings/developers">discogs.com/settings/developers</a>
   and click <i>Generate new token</i>.<br>
   <b>Last.fm:</b> at <a href="https://www.last.fm/api/account/create">last.fm/api/account/create</a> fill in a
   name and description; copy the <i>API key</i> (you don't need the <i>shared secret</i>).</p>
<h3>What happens to your tracks</h3>
<ul>
  <li><b>Genres:</b> each track goes to its genre folder (e.g. <code>House\\Tech House</code>).
      Untagged: by pack name; otherwise it goes to <code>No Genre</code>.</li>
  <li><b>Duplicates:</b> the <b>Extended Mix</b> is kept; otherwise the longest; then lossless.
      The others go to the Windows <b>Recycle Bin</b>.</li>
  <li><b>Other:</b> genres with few tracks (Pop, Hardstyle, Rock…). The real genre stays in the tag.</li>
  <li><b>BPM:</b> <code>No Genre</code> and <code>Other</code> are split into BPM folders.</li>
  <li><b>Tags:</b> the folder's genre is written to the Genre tag; download-site names are removed from Album, Title, etc.</li>
</ul>
<h3>Made a mistake?</h3>
<p><b>Undo last run</b> moves back the files moved in the last run.
   Files sent to the Recycle Bin are restored from Windows (Recycle Bin › Restore).</p>
<h3>Where data is kept</h3>
<p class="muted">Settings and keys: <code>%APPDATA%\\OrganizadorMusica\\config.json</code> (this PC only).<br>
   Caches and logs: <code>%APPDATA%\\OrganizadorMusica\\bibliotecas</code> — outside your music folder,
   so they don't show up if you share it on Soulseek / Nicotine+.</p>
<h3>Common problems</h3>
<ul>
  <li><b>.rar won't extract:</b> install <a href="https://7-zip.org">7-Zip</a>.</li>
  <li><b>Many tracks in "No Genre":</b> check your keys; turn on MusicBrainz (slower).</li>
  <li><b>Tracks with "!" in rekordbox:</b> normal after organizing — run Auto Relocate.</li>
</ul>
""",
}

ABOUT = {
    "pt": """
<h2>Organizador de Música</h2>
<p class="muted">Versão {v}</p>
<p>Arruma bibliotecas de música de DJ: extrai packs, separa por género e subgénero, remove repetidas
   ficando com a Extended Mix, procura géneros online e limpa as tags.</p>
<h3>Desenvolvido por</h3>
<p><b>{a}</b> — <a href="{r}">{rs}</a></p>
<h3>Construído com</h3>
<p class="muted">Python · PySide6 (Qt) · mutagen · Send2Trash · librosa (opcional)<br>
   Dados de géneros: Discogs, Last.fm e MusicBrainz.<br>
   Este programa não está associado ao rekordbox, Serato, Beatport, Discogs, Last.fm ou MusicBrainz.</p>
<h3>Licença</h3>
<p class="muted">MIT — podes usar, alterar e partilhar livremente.</p>
""",
    "en": """
<h2>Music Organizer</h2>
<p class="muted">Version {v}</p>
<p>Tidies DJ music libraries: extracts packs, sorts by genre and subgenre, removes duplicates keeping the
   Extended Mix, looks up genres online and cleans tags.</p>
<h3>Developed by</h3>
<p><b>{a}</b> — <a href="{r}">{rs}</a></p>
<h3>Built with</h3>
<p class="muted">Python · PySide6 (Qt) · mutagen · Send2Trash · librosa (optional)<br>
   Genre data: Discogs, Last.fm and MusicBrainz.<br>
   This program is not affiliated with rekordbox, Serato, Beatport, Discogs, Last.fm or MusicBrainz.</p>
<h3>License</h3>
<p class="muted">MIT — free to use, modify and share.</p>
""",
}


def help_html():
    return _CSS + HELP.get(lang(), HELP["en"])


def about_html():
    return _CSS + ABOUT.get(lang(), ABOUT["en"]).format(v=__version__, a=AUTHOR, r=REPO, rs=REPO.replace("https://", ""))


def _browser(html):
    b = QTextBrowser(openExternalLinks=True)
    b.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
    b.setHtml(html)
    return b


class InfoDialog(QDialog):
    def __init__(self, title, html, parent=None, size=(640, 620)):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(*size)
        self.setStyleSheet(f"QDialog {{ background: {C['card']}; }}")
        close = QPushButton(t("btn.close"), objectName="primary", cursor=Qt.PointingHandCursor)
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.addWidget(_browser(html), 1)
        lay.addLayout(row)


class TermsDialog(QDialog):
    """First run: choose the language and accept the terms. accept() only with the box ticked."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.resize(680, 640)
        self.setStyleSheet(f"QDialog {{ background: {C['card']}; }}")
        self.combo = QComboBox()
        for code, name in LANGS.items():
            self.combo.addItem(name, code)
        self.combo.setCurrentIndex(list(LANGS).index(lang()))
        self.combo.currentIndexChanged.connect(self._lang_changed)
        self.title = QLabel(objectName="cardTitle")
        self.intro = QLabel(objectName="hint")
        self.text = _browser("")
        self.check = QCheckBox()
        self.accept_btn = QPushButton(objectName="primary", cursor=Qt.PointingHandCursor, enabled=False)
        self.exit_btn = QPushButton(cursor=Qt.PointingHandCursor)
        self.check.toggled.connect(self.accept_btn.setEnabled)
        self.accept_btn.clicked.connect(self.accept)
        self.exit_btn.clicked.connect(self.reject)
        top = QHBoxLayout()
        top.addWidget(self.title, 1)
        top.addWidget(self.combo)
        row = QHBoxLayout()
        row.addWidget(self.check, 1)
        row.addWidget(self.exit_btn)
        row.addWidget(self.accept_btn)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.addLayout(top)
        lay.addWidget(self.intro)
        lay.addWidget(self.text, 1)
        lay.addLayout(row)
        self._retranslate()

    def _lang_changed(self):
        set_lang(self.combo.currentData())
        self._retranslate()

    def _retranslate(self):
        self.setWindowTitle(t("terms.title"))
        self.title.setText(t("terms.title"))
        self.intro.setText(t("terms.intro"))
        body = termos.TERMS.get(lang(), termos.TERMS["en"]).replace("&", "&amp;").replace("<", "&lt;")
        self.text.setHtml(_CSS + "<p>" + body.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>")
        self.check.setText(t("terms.check"))
        self.accept_btn.setText(t("terms.accept"))
        self.exit_btn.setText(t("terms.exit"))


class TermsView(InfoDialog):
    """Read-only terms (from the header), already accepted."""

    def __init__(self, parent=None):
        body = termos.TERMS.get(lang(), termos.TERMS["en"]).replace("&", "&amp;").replace("<", "&lt;")
        super().__init__(t("terms.title"), _CSS + "<p>" + body.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>", parent)
