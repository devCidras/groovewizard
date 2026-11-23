# Avisos de terceiros / Third-party notices

Cratekeeper é software livre sob a **GNU General Public License v3.0 ou posterior** (ficheiro `LICENSE`).
O instalador para Windows inclui os componentes abaixo, cada um com a sua licença (textos nesta pasta).

Cratekeeper is free software under the **GNU General Public License v3.0 or later** (`LICENSE`).
The Windows installer bundles the components below, each under its own license (texts in this folder).

| Componente / Component | Versão | Licença / License | Código-fonte / Source |
|---|---|---|---|
| mutagen | 1.48.1 | GPL-2.0-or-later (`mutagen-GPL-2.0-or-later.txt`) | https://github.com/quodlibet/mutagen |
| PySide6 / Shiboken6 (Qt for Python) | 6.12.0 | LGPL-3.0 (`LGPL-3.0.txt` + `LICENSE` GPL-3.0) | https://code.qt.io/cgit/pyside/pyside-setup.git/ |
| Qt 6 (Core, Gui, Widgets, Svg) | 6.12.0 | LGPL-3.0 (`LGPL-3.0.txt`) | https://download.qt.io/official_releases/qt/ |
| Send2Trash | 2.2.0 | BSD-3-Clause (`Send2Trash-BSD-3-Clause.txt`) | https://github.com/arsenetar/send2trash |
| Python | 3.14 | PSF License (`Python-PSF.txt`) | https://www.python.org/downloads/source/ |
| PyInstaller (bootloader) | 6.22.3 | GPL-2.0 with bootloader exception (`PyInstaller-GPL-2.0-bootloader-exception.txt`) | https://github.com/pyinstaller/pyinstaller |
| Microsoft Visual C++ Runtime | — | Microsoft redistributable | — |

## Qt / LGPL

As bibliotecas Qt são carregadas dinamicamente (ficheiros `Qt6*.dll` na pasta `_internal\PySide6` da instalação)
e podem ser substituídas por versões compatíveis modificadas pelo utilizador. O instalador inclui apenas módulos Qt
disponíveis sob LGPL-3.0.

The Qt libraries are dynamically loaded (`Qt6*.dll` in the installation's `_internal\PySide6` folder) and may be
replaced by the user with compatible modified versions. The installer only ships Qt modules available under LGPL-3.0.

## Oferta escrita de código-fonte / Written source offer

O código-fonte completo do Cratekeeper de cada versão está no GitHub, na tag correspondente
(https://github.com/devCidras/cratekeeper/releases), juntamente com `build.ps1` e `requirements.txt` com as versões
exatas usadas. Durante pelo menos três anos após cada versão, qualquer pessoa pode pedir uma cópia do código-fonte
correspondente das bibliotecas GPL/LGPL incluídas (mutagen, PySide6/Shiboken6, Qt) abrindo uma *issue* no repositório;
o pedido é atendido sem custo além do eventual meio físico.

The complete Cratekeeper source of every version is on GitHub at the matching tag, together with `build.ps1` and
`requirements.txt` pinning the exact versions used. For at least three years after each release, anyone may request a
copy of the corresponding source of the bundled GPL/LGPL components (mutagen, PySide6/Shiboken6, Qt) by opening an
issue in the repository; it is provided at no charge beyond any physical medium.

## Marcas / Trademarks

rekordbox, Serato, Beatport, Discogs, Last.fm, MusicBrainz e Windows são marcas dos respetivos donos. O Cratekeeper
não está associado a nenhum deles. / are trademarks of their respective owners; Cratekeeper is not affiliated with them.
