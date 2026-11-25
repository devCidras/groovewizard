"""Help, About and Terms dialogs (Portuguese / English)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QTextBrowser,
                               QVBoxLayout)

from . import __version__, termos
from .i18n import LANGS, lang, set_lang, t
from .theme import C

AUTHOR = "devCidras"
REPO = "https://github.com/devCidras/groovewizard"

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
  <li><b>Fecha o rekordbox / Serato.</b> A app mexe nos ficheiros e eles não podem estar abertos.</li>
  <li><b>Biblioteca:</b> escolhe a pasta onde tens as músicas (ex.: <code>D:\\musica</code>). Os packs que
      descarregas (.zip, .rar) podem ficar lá dentro: a app descompacta-os.</li>
  <li><b>Fontes online</b> (opcional): cola as chaves grátis do Discogs e do Last.fm. Ajudam a descobrir o género
      das faixas que não o têm.</li>
  <li><b>Passos:</b> liga só o que queres que a app faça.</li>
  <li><b>Pré-visualizar</b> não mexe em nada e mostra as mudanças que consegue prever. Não inclui faixas ainda dentro
      dos packs, resultados online nem limpeza de sites dentro das tags. Depois aparece <b>Ver lista</b>.</li>
  <li><b>Organizar</b> faz as mudanças. Podes <b>Cancelar</b> a meio: o que já foi feito fica feito.</li>
  <li>No fim, no <b>rekordbox</b>: <i>Ficheiro › Gerir faixas inexistentes › Auto Relocate</i> (escolhe a pasta) e
      depois, na Coleção, <i>Ctrl+A › botão direito › Recarregar tag</i>.</li>
</ol>
<h3>Criar as chaves (grátis, 2 minutos)</h3>
<p><b>Discogs:</b> entra em <a href="https://www.discogs.com/settings/developers">discogs.com/settings/developers</a>
   e carrega em <i>Generate new token</i>.<br>
   <b>Last.fm:</b> em <a href="https://www.last.fm/api/account/create">last.fm/api/account/create</a> preenche nome e
   descrição e copia a <i>API key</i>.</p>
<h3>O que a app faz às faixas</h3>
<ul>
  <li><b>Género:</b> cada faixa vai para a pasta do seu género (ex.: <code>House\\Tech House</code>). Se a faixa não
      disser o género, usa o nome do pack; se não houver nada, vai para <code>Sem Genero</code>, separada por BPM.
      Se a faixa não traz o BPM, a app mede-o (exceto M4A); sem batida clara vai para <code>BPM desconhecido</code>.</li>
  <li><b>Repetidas:</b> se tens a mesma faixa duas vezes, fica a melhor (a Extended, senão a mais longa). A outra vai
      para a <b>quarentena</b>. Por defeito, Radio Edit e Club Mix contam como a mesma faixa que Original/Extended.</li>
  <li><b>Outros:</b> géneros de uma lista fixa (Pop, Hardstyle, Blues, Dub…) ficam juntos em <code>Outros</code>.</li>
  <li><b>Tags:</b> grava o género dentro da faixa e tira nomes de sites (ex.: <code>www.djsoundtop.com</code>) do
      título, álbum e comentários.</li>
  <li><b>Capas</b> (opção <i>Pôr capas</i>): as faixas sem capa recebem a capa do lançamento (Deezer e, com a chave,
      Discogs). Uma capa que já exista nunca é trocada. Em <i>Também nas antigas…</i>, podes incluir as faixas antigas
      sem capa; se não encontrar uma capa, deixa-as como estão. No rekordbox, faz <i>Recarregar tag</i> para a ver.</li>
  <li><b>Capas de sites</b> (opção <i>Trocar capas de sites</i>): tira as capas que são publicidade (ex.: djsoundtop)
      ou genéricas (ex.: símbolo do Beatport) e procura a verdadeira. Se não a encontrar, a faixa fica sem capa. Se
      aparecer um site novo, carrega em <i>Ver capas repetidas…</i> e marca a capa dele.</li>
</ul>
<h3>Nomes das faixas</h3>
<ul>
  <li>Nas <b>faixas novas</b> o site e o número de faixa saem também do nome do ficheiro
      (<code>05. Artista - Título</code> passa a <code>Artista - Título</code>). Com a opção <i>Pôr nomes Artista - Título</i>,
      ficam por exemplo <code>Fisher - Losing It (Extended Mix)</code>.</li>
  <li>As faixas dos packs mudam de nome logo. Outras faixas novas (que puseste soltas na pasta) só depois de
      confirmares, porque podem já estar no rekordbox.</li>
  <li>As <b>faixas que já tinhas</b> nunca mudam de nome, a não ser que ligues <i>Limpar o nome das faixas
      antigas</i>. Nesse caso a app pergunta antes; depois pode ser preciso usar Auto Relocate. Confirma os cues no
      teu programa de DJ.</li>
  <li>Dica: organiza <b>antes</b> de importares as faixas novas no rekordbox.</li>
</ul>
<h3>Opções úteis</h3>
<ul>
  <li><b>Pastas protegidas</b> (em Biblioteca): pastas em que a app nunca toca, por exemplo os teus edits.</li>
  <li><b>Só faixas novas:</b> fica disponível depois da primeira organização completa desta biblioteca. Normalmente
      arruma só o que chegou depois. Em <i>Também nas antigas…</i>, escolhes separadamente quais os passos a repetir
      nas faixas antigas: arrumar, remover repetidas, procurar género online, separar por BPM, gravar género na tag,
      limpar sites das tags, pôr capas ou trocar capas de sites. Todas estas escolhas começam desligadas e só atuam
      quando o respetivo passo está ligado. Arrumar, procurar género online e separar por BPM podem mover faixas;
      remover repetidas pode enviá-las para a quarentena; trocar capas de sites pode deixar uma faixa sem capa.
      Usa Pré-visualizar e faz uma cópia de segurança. A comparação de repetidas pode ler todas as faixas, mas não
      altera as antigas sem essa escolha.</li>
  <li><b>Relatório:</b> mostra as faixas com problemas, sem mexer em nada: sem artista ou título, sem género, MP3 de
      menor qualidade ou muito curtas. Abre no Excel.</li>
</ul>
<h3>Enganei-me, e agora?</h3>
<p><b>Desfazer…</b> mostra as últimas organizações. Escolhe até onde queres voltar: as faixas regressam ao sítio onde
   estavam, as repetidas saem da quarentena e as tags voltam ao que eram. Se algum ficheiro estiver aberto noutro
   programa, fecha-o e carrega outra vez.<br>
   <b>Ver quarentena</b> abre a pasta (escondida) onde estão as faixas removidas, para veres ou copiares alguma de volta.<br>
   <b>Esvaziar quarentena</b> manda já para a Reciclagem o que está na quarentena. A partir daí o Desfazer já não
   recupera essas faixas.</p>
<h3>Bom saber</h3>
<ul>
  <li>A app lembra-se das faixas que já viu, para saber quais são novas. Depois de atualizares para a versão 1.5 ou
      mais recente, a primeira organização lê um pedaço de cada faixa; numa biblioteca grande demora uns minutos a mais, só dessa vez.</li>
  <li>As definições e chaves ficam em <code>%APPDATA%\\GrooveWizard</code>, fora da pasta das músicas (não aparecem
      se a partilhares no Soulseek / Nicotine+).</li>
</ul>
<h3>Problemas comuns</h3>
<ul>
  <li><b>Os .rar não descompactam:</b> instala o <a href="https://7-zip.org">7-Zip</a>.</li>
  <li><b>Muitas faixas em "Sem Genero":</b> confirma as chaves (botão Verificar) e liga o MusicBrainz.</li>
  <li><b>Faixas com "!" no rekordbox:</b> é normal depois de organizar. Faz o Auto Relocate.</li>
</ul>
""",
    "en": """
<h2>How to use</h2>
<ol>
  <li><b>Close rekordbox / Serato.</b> The app works on the files and they can't be open.</li>
  <li><b>Library:</b> choose the folder with your music (e.g. <code>D:\\Music</code>). The packs you download
      (.zip, .rar) can stay in there: the app unpacks them.</li>
  <li><b>Online sources</b> (optional): paste your free Discogs and Last.fm keys. They help find the genre of tracks
      that don't have one.</li>
  <li><b>Steps:</b> turn on only what you want the app to do.</li>
  <li><b>Preview</b> changes nothing and shows what it can predict. It excludes tracks still inside archives, online
      results and website cleanup inside tags. Then <b>See list</b> lets you untick tracks.</li>
  <li><b>Organize</b> makes the changes. You can <b>Cancel</b> halfway: what's done stays done.</li>
  <li>Afterwards, in <b>rekordbox</b>: <i>File › Manage Missing Files › Auto Relocate</i> (pick the folder), then in
      the Collection <i>Ctrl+A › right-click › Reload Tag</i>.</li>
</ol>
<h3>Getting the keys (free, 2 minutes)</h3>
<p><b>Discogs:</b> go to <a href="https://www.discogs.com/settings/developers">discogs.com/settings/developers</a>
   and click <i>Generate new token</i>.<br>
   <b>Last.fm:</b> at <a href="https://www.last.fm/api/account/create">last.fm/api/account/create</a> fill in a name
   and description and copy the <i>API key</i>.</p>
<h3>What the app does to your tracks</h3>
<ul>
  <li><b>Genre:</b> each track goes to the folder of its genre (e.g. <code>House\\Tech House</code>). If the track has
      no genre, the pack name is used; with nothing at all it goes to <code>No Genre</code>, split by BPM.
      If a track doesn't have its BPM, the app measures it (except M4A); with no clear beat it goes to <code>BPM unknown</code>.</li>
  <li><b>Duplicates:</b> if you have the same track twice, the best one stays (the Extended, else the longest). The
      other goes to <b>quarantine</b>. By default Radio Edit and Club Mix count as the same track as Original/Extended.</li>
  <li><b>Other:</b> genres on a fixed list (Pop, Hardstyle, Blues, Dub…) go together in <code>Other</code>.</li>
  <li><b>Tags:</b> saves the genre inside the track and removes website names (e.g. <code>www.djsoundtop.com</code>)
      from the title, album and comments.</li>
  <li><b>Cover art</b> (option <i>Add cover art</i>): tracks without a cover get the release's cover (Deezer and, with
      the key, Discogs). An existing cover is never replaced. Under <i>Also on old tracks…</i>, you can include old
      tracks without artwork; if nothing is found, they stay unchanged. In rekordbox, use <i>Reload Tag</i> to see it.</li>
  <li><b>Site covers</b> (option <i>Replace site covers</i>): takes out covers that are ads (e.g. djsoundtop) or generic
      (e.g. the Beatport logo) and looks for the real one. If it isn't found, the track is left without a cover. If a
      new site shows up, press <i>See repeated covers…</i> and tick its cover.</li>
</ul>
<h3>Track names</h3>
<ul>
  <li>For <b>new tracks</b> the site and the track number also come out of the file name
      (<code>05. Artist - Title</code> becomes <code>Artist - Title</code>). With the option <i>Name new tracks Artist -
      Title</i> they become, for example, <code>Fisher - Losing It (Extended Mix)</code>.</li>
  <li>Tracks from packs are renamed right away. Other new tracks (that you dropped in the folder) only after you
      confirm, because they may already be in rekordbox.</li>
  <li><b>Tracks you already had</b> never change name, unless you turn on <i>Clean up old tracks' names</i>.
      Then the app asks first; afterwards you may need Auto Relocate. Check the cues in your DJ software.</li>
  <li>Tip: organize <b>before</b> importing new tracks into rekordbox.</li>
</ul>
<h3>Useful options</h3>
<ul>
  <li><b>Protected folders</b> (under Library): folders the app never touches, for example your own edits.</li>
  <li><b>Only new tracks:</b> becomes available after the first completed full organize of this library. Normally it
      only sorts later arrivals. Under <i>Also on old tracks…</i>, choose independently which steps to repeat on old
      tracks: genre sorting, duplicate removal, online genre lookup, BPM sorting, writing genre tags, cleaning
      website names from tags, adding missing art, or replacing site covers. Every choice starts off and requires its
      main step to be on. Genre and BPM sorting can move tracks; duplicates can enter quarantine; replacing site
      covers can leave a track without art. Use Preview and back up first. Duplicate comparison may read every
      track, but will not change old ones unless selected.</li>
  <li><b>Report:</b> shows tracks with problems, without changing anything: no artist or title, no genre,
      lower-quality MP3 or very short. Opens in Excel.</li>
</ul>
<h3>Made a mistake?</h3>
<p><b>Undo…</b> lists your recent organizes. Choose how far back to go: tracks return to where they were, duplicates
   come out of quarantine and tags go back to what they were. If a file is open in another program, close it and
   press Undo again.<br>
   <b>Open quarantine</b> opens the (hidden) folder with the removed tracks, to look at them or copy one back.<br>
   <b>Empty quarantine</b> sends what's in quarantine to the Recycle Bin now. After that, Undo can't bring those
   tracks back.</p>
<h3>Good to know</h3>
<ul>
  <li>The app remembers the tracks it has seen, to tell which ones are new. After updating to version 1.5 or later, the
      first organize reads a piece of every track; in a big library that takes a few extra minutes, only that once.</li>
  <li>Settings and keys are kept in <code>%APPDATA%\\GrooveWizard</code>, outside your music folder (they don't show
      up if you share it on Soulseek / Nicotine+).</li>
</ul>
<h3>Common problems</h3>
<ul>
  <li><b>.rar files don't unpack:</b> install <a href="https://7-zip.org">7-Zip</a>.</li>
  <li><b>Many tracks in "No Genre":</b> check your keys (Check button) and turn on MusicBrainz.</li>
  <li><b>Tracks with "!" in rekordbox:</b> normal after organizing. Run Auto Relocate.</li>
</ul>
""",
}

ABOUT = {
    "pt": """
<h2>GrooveWizard</h2>
<p class="muted">Versão {v}</p>
<p>Arruma bibliotecas de música de DJ: extrai packs, separa por género e subgénero, remove repetidas
   ficando com a Extended Mix, procura géneros online e limpa as tags.</p>
<h3>Desenvolvido por</h3>
<p><b>{a}</b> — <a href="{r}">{rs}</a></p>
<h3>Construído com</h3>
<p class="muted">Python · PySide6 (Qt) · mutagen · Send2Trash · numpy · soundfile (libsndfile)<br>
   Dados de géneros: Discogs, Last.fm e MusicBrainz.<br>
   Este programa não está associado ao rekordbox, Serato, Beatport, Discogs, Last.fm ou MusicBrainz.</p>
<h3>Licença</h3>
<p class="muted">GPL-3.0 — podes usar, estudar, alterar e partilhar; versões alteradas que distribuas têm de manter o código aberto. Componentes de terceiros e as suas licenças: pasta <code>licencas</code> da instalação.</p>
""",
    "en": """
<h2>GrooveWizard</h2>
<p class="muted">Version {v}</p>
<p>Tidies DJ music libraries: extracts packs, sorts by genre and subgenre, removes duplicates keeping the
   Extended Mix, looks up genres online and cleans tags.</p>
<h3>Developed by</h3>
<p><b>{a}</b> — <a href="{r}">{rs}</a></p>
<h3>Built with</h3>
<p class="muted">Python · PySide6 (Qt) · mutagen · Send2Trash · numpy · soundfile (libsndfile)<br>
   Genre data: Discogs, Last.fm and MusicBrainz.<br>
   This program is not affiliated with rekordbox, Serato, Beatport, Discogs, Last.fm or MusicBrainz.</p>
<h3>License</h3>
<p class="muted">GPL-3.0 — free to use, study, modify and share; modified versions you distribute must stay open source. Third-party components and their licenses: <code>licencas</code> folder of the installation.</p>
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
