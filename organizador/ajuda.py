"""Help and About dialogs."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout

from . import __version__
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

HELP = _CSS + f"""
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
   Caches e registos: <code>%APPDATA%\\OrganizadorMusica\\bibliotecas</code> — fora da pasta das músicas, para não aparecerem
   se a partilhares no Soulseek / Nicotine+.</p>

<h3>Problemas comuns</h3>
<ul>
  <li><b>.rar não extrai:</b> instala o <a href="https://7-zip.org">7-Zip</a>.</li>
  <li><b>Muitas faixas em "Sem Genero":</b> confirma as chaves; liga o MusicBrainz (mais lento).</li>
  <li><b>Faixas com "!" no rekordbox:</b> é normal depois de organizar — faz o Auto Relocate.</li>
</ul>
"""

ABOUT = _CSS + f"""
<h2>Organizador de Música</h2>
<p class="muted">Versão {__version__}</p>
<p>Arruma bibliotecas de música de DJ: extrai packs, separa por género e subgénero, remove repetidas
   ficando com a Extended Mix, procura géneros online e limpa as tags.</p>
<h3>Desenvolvido por</h3>
<p><b>{AUTHOR}</b> — <a href="{REPO}">{REPO.replace('https://', '')}</a></p>
<h3>Construído com</h3>
<p class="muted">Python · PySide6 (Qt) · mutagen · Send2Trash · librosa (opcional)<br>
   Dados de géneros: Discogs, Last.fm e MusicBrainz.<br>
   Este programa não está associado ao rekordbox, Serato, Beatport, Discogs, Last.fm ou MusicBrainz.</p>
<h3>Licença</h3>
<p class="muted">MIT — podes usar, alterar e partilhar livremente.</p>
"""


class InfoDialog(QDialog):
    def __init__(self, title, html, parent=None, size=(640, 620)):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(*size)
        self.setStyleSheet(f"QDialog {{ background: {C['card']}; }}")
        text = QTextBrowser(openExternalLinks=True)
        text.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        text.setHtml(html)
        close = QPushButton("Fechar", objectName="primary", cursor=Qt.PointingHandCursor)
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.addWidget(text, 1)
        lay.addLayout(row)
