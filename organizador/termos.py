"""Terms and Conditions shown in the installer and on first run. Bump VERSION when the text changes (asks again)."""

VERSION = "7"

TERMS = {
    "pt": """TERMOS E CONDIÇÕES DE UTILIZAÇÃO — GrooveWizard

1. O que o programa faz
O GrooveWizard move, renomeia e altera as etiquetas (tags) de ficheiros de áudio na pasta que escolheres. Pode extrair ficheiros compactados e enviar ficheiros (repetidas, compactados, ficheiros que não são música) para uma pasta de quarentena dentro da biblioteca, onde ficam 30 dias antes de irem para a Reciclagem do Windows.

2. Responsabilidade e cópias de segurança
Usas o programa por tua conta e risco. Recomendamos que faças uma cópia de segurança das tuas músicas e da biblioteca do teu software de DJ (rekordbox, Serato, etc.) antes de usar. O programa regista as alterações (ficheiros movidos, removidos e tags originais) para poderes desfazer a última execução, mas não garante a recuperação de todas as alterações (por exemplo, depois de esvaziares a quarentena).

3. Sem garantia
O programa é fornecido "tal como está", sem garantias de qualquer tipo, nos termos da licença GPL-3.0. Os autores não são responsáveis por perda de dados, de cues, de playlists, de análises ou por qualquer outro dano resultante da utilização.

4. Serviços de terceiros
Se ativares a procura online, o programa envia o artista e o título das faixas ao Discogs, e só o artista ao Last.fm e/ou ao MusicBrainz, e fica sujeito aos termos desses serviços. As chaves de API são tuas, ficam guardadas apenas neste computador e não são enviadas aos autores.

5. Privacidade
O programa não recolhe nem envia dados para os autores. Ao abrir, pergunta sempre ao GitHub se há uma versão nova (o GitHub vê o teu IP, como em qualquer pedido na internet). Definições, chaves, caches e registos ficam em %APPDATA%\\GrooveWizard no teu computador.

6. Direitos sobre a música
O programa não descarrega nem distribui música. És responsável por teres o direito de usar os ficheiros que organizas.

7. Marcas
rekordbox, Serato, Beatport, Discogs, Last.fm e MusicBrainz são marcas dos respetivos donos. Este programa não está associado a nenhum deles.

8. Licença
Software livre sob a GNU General Public License v3.0 ou posterior (ficheiro LICENSE). Inclui componentes de terceiros com as suas próprias licenças (pasta "licencas" da instalação).

Ao aceitar, confirmas que leste e concordas com estes termos.
""",
    "en": """TERMS AND CONDITIONS OF USE — GrooveWizard

1. What the program does
GrooveWizard moves, renames and edits the tags of audio files in the folder you choose. It can extract archives and send files (duplicates, archives, non-music files) to a quarantine folder inside the library, kept 30 days before going to the Windows Recycle Bin.

2. Responsibility and backups
You use the program at your own risk. We recommend backing up your music and your DJ software library (rekordbox, Serato, etc.) before using it. The program logs its changes (moved and removed files, original tags) so you can undo the last run, but it does not guarantee that every change can be reverted (for example, after the quarantine is emptied).

3. No warranty
The program is provided "as is", without warranty of any kind, under the GPL-3.0 license. The authors are not liable for loss of data, cues, playlists, analysis or any other damage arising from its use.

4. Third-party services
If you enable the online lookup, the program sends track artist and title to Discogs, and only the artist to Last.fm and/or MusicBrainz, and is subject to those services' terms. API keys are yours, are stored only on this computer and are never sent to the authors.

5. Privacy
The program does not collect or send any data to the authors. On every start-up it asks GitHub whether a new version exists (GitHub sees your IP, as with any internet request). Settings, keys, caches and logs are kept in %APPDATA%\\GrooveWizard on your computer.

6. Music rights
The program does not download or distribute music. You are responsible for having the right to use the files you organize.

7. Trademarks
rekordbox, Serato, Beatport, Discogs, Last.fm and MusicBrainz are trademarks of their respective owners. This program is not affiliated with any of them.

8. License
Free software under the GNU General Public License v3.0 or later (LICENSE file). It bundles third-party components under their own licenses ("licencas" folder of the installation).

By accepting, you confirm that you have read and agree to these terms.
""",
}
