"""UI translations. Add a language: add its code to LANGS and a column to every entry (missing -> English)."""

LANGS = {"pt": "Português", "en": "English"}
_lang = "pt"


def set_lang(code):
    global _lang
    _lang = code if code in LANGS else "en"


def lang():
    return _lang


def t(key, **kw):
    entry = S.get(key)
    if entry is None:
        return key
    text = entry.get(_lang)
    if text is None:  # "" is a valid translation (e.g. a blank state label)
        text = entry.get("en", key)
    return text.format(**kw) if kw else text


def report_label(key):
    """Report keys are 'id' or 'id|param' (e.g. 'moved|Tech House')."""
    rid, _, param = key.partition("|")
    return t("rep." + rid, x=param)


def system_lang():
    import locale
    try:
        code = (locale.getlocale()[0] or "").lower()
    except Exception:
        code = ""
    return "pt" if code.startswith(("pt", "portuguese")) else "en"


S = {
    # header
    "app.title": {"pt": "Cratekeeper", "en": "Cratekeeper"},
    "app.subtitle": {"pt": "Arruma a tua biblioteca por género, sem repetidas, com as tags limpas.",
                     "en": "Sorts your library by genre, without duplicates, with clean tags."},
    "btn.help": {"pt": "Ajuda", "en": "Help"},
    "btn.help_tip": {"pt": "Como usar (F1)", "en": "How to use (F1)"},
    "btn.about": {"pt": "Sobre", "en": "About"},
    "btn.about_tip": {"pt": "Quem fez, versão, licença", "en": "Who made it, version, license"},
    "lang.tip": {"pt": "Idioma", "en": "Language"},
    # library
    "card.library": {"pt": "Biblioteca", "en": "Library"},
    "card.library_hint": {"pt": "A pasta onde estão as tuas músicas. Fecha o rekordbox / Serato antes de organizar.",
                          "en": "The folder with your music. Close rekordbox / Serato before organizing."},
    "folder.placeholder": {"pt": r"ex.: D:\musica", "en": r"e.g. D:\Music"},
    "folder.pick": {"pt": "Escolher…", "en": "Browse…"},
    "folder.dialog": {"pt": "Pasta das músicas", "en": "Music folder"},
    # online
    "card.online": {"pt": "Fontes online", "en": "Online sources"},
    "card.online_hint": {"pt": "Chaves grátis, guardadas só neste PC. {discogs} · {lastfm}",
                         "en": "Free keys, stored only on this PC. {discogs} · {lastfm}"},
    "link.discogs": {"pt": "Criar token Discogs", "en": "Get a Discogs token"},
    "link.lastfm": {"pt": "Criar chave Last.fm", "en": "Get a Last.fm key"},
    "btn.show": {"pt": "Mostrar", "en": "Show"},
    "btn.hide": {"pt": "Esconder", "en": "Hide"},
    # steps
    "card.steps": {"pt": "Passos", "en": "Steps"},
    "card.more": {"pt": "Mais opções", "en": "More options"},
    "opt.extract": {"pt": "Extrair packs", "en": "Extract packs"},
    "opt.extract_d": {"pt": "Descompacta .zip, .rar e .7z (os .rar/.7z precisam do 7-Zip).",
                      "en": "Unpacks .zip, .rar and .7z (.rar/.7z need 7-Zip)."},
    "opt.organize": {"pt": "Arrumar por género", "en": "Sort by genre"},
    "opt.organize_d": {"pt": "Pela tag Genre; sem tag, pelo nome do pack.", "en": "By the Genre tag; untagged: by pack name."},
    "opt.dedupe": {"pt": "Remover repetidas", "en": "Remove duplicates"},
    "opt.dedupe_d": {"pt": "Fica a Extended, senão a mais longa. As outras vão para a quarentena (30 dias).",
                     "en": "Keeps the Extended Mix, else the longest. The rest go to quarantine (30 days)."},
    "opt.online": {"pt": "Procurar género online", "en": "Look up genres online"},
    "opt.online_d": {"pt": "Discogs e Last.fm para as faixas sem género.", "en": "Discogs and Last.fm for tracks with no genre."},
    "opt.bpm_folders": {"pt": "Separar por BPM", "en": "Split by BPM"},
    "opt.bpm_folders_d": {"pt": "As faixas sem género ficam em pastas de BPM (122-128, 128-135…).",
                          "en": "Tracks with no genre go into BPM folders (122-128, 128-135…)."},
    "opt.write_tags": {"pt": "Gravar género na tag", "en": "Write genre to tags"},
    "opt.write_tags_d": {"pt": "O rekordbox / Serato passam a mostrar o género certo.",
                         "en": "rekordbox / Serato will show the right genre."},
    "opt.clean_sites": {"pt": "Limpar sites das tags", "en": "Remove sites from tags"},
    "opt.clean_sites_d": {"pt": "Tira 'djsoundtop.com' e afins do Álbum, Título, Comentário…",
                          "en": "Strips 'djsoundtop.com' and the like from Album, Title, Comment…"},
    "opt.families": {"pt": "Agrupar em pastas-mãe", "en": "Group into parent folders"},
    "opt.families_d": {"pt": "House / Tech House, Techno / Hard Techno, Melodic & Indie…",
                       "en": "House / Tech House, Techno / Hard Techno, Melodic & Indie…"},
    "opt.musicbrainz": {"pt": "Usar também o MusicBrainz", "en": "Also use MusicBrainz"},
    "opt.musicbrainz_d": {"pt": "Sem chave, mas lento (1 pedido por segundo).", "en": "No key needed, but slow (1 request per second)."},
    "opt.merge_versions": {"pt": "Radio Edit / Club Mix contam como repetidas", "en": "Radio Edit / Club Mix count as duplicates"},
    "opt.merge_versions_d": {"pt": "Desligado: só Original e Extended são a mesma faixa; as outras versões ficam.",
                             "en": "Off: only Original and Extended are the same track; other versions are kept."},
    "opt.delete_archives": {"pt": "Enviar compactados para a quarentena", "en": "Move archives to quarantine"},
    "opt.delete_archives_d": {"pt": "Depois de extraídos com sucesso.", "en": "After they were extracted successfully."},
    # actions
    "btn.run": {"pt": "Organizar", "en": "Organize"},
    "btn.preview": {"pt": "Pré-visualizar", "en": "Preview"},
    "btn.preview_tip": {"pt": "Mostra o que ia mudar, sem mexer em nada.", "en": "Shows what would change, without touching anything."},
    "btn.cancel": {"pt": "Cancelar", "en": "Cancel"},
    "btn.undo": {"pt": "Desfazer última", "en": "Undo last run"},
    "btn.undo_tip": {"pt": "Devolve os ficheiros movidos na última vez.", "en": "Moves back the files moved in the last run."},
    "btn.purge": {"pt": "Esvaziar quarentena", "en": "Empty quarantine"},
    "btn.purge_tip": {"pt": "Repetidas e lixo removidos ficam 30 dias em _quarentena; isto envia-os já para a Reciclagem.",
                      "en": "Removed duplicates and junk stay 30 days in _quarentena; this sends them to the Recycle Bin now."},
    "msg.purge_confirm": {"pt": "Enviar tudo o que está na quarentena para a Reciclagem?\nDepois disto o Desfazer já não recupera essas faixas.",
                          "en": "Send everything in quarantine to the Recycle Bin?\nUndo will no longer bring those files back."},
    "log.kind.purge": {"pt": "Esvaziar quarentena", "en": "Empty quarantine"},
    "btn.check": {"pt": 'Verificar', "en": 'Check'},
    "btn.check_tip": {"pt": 'Testa a chave agora (um pedido ao serviço).', "en": 'Tests the key now (one request to the service).'},
    "key.checking": {"pt": 'A verificar…', "en": 'Checking…'},
    "key.ok": {"pt": '✓ Válida {detail}', "en": '✓ Valid {detail}'},
    "key.invalid": {"pt": '✗ Inválida — confirma que copiaste a chave toda', "en": '✗ Invalid — check you copied the whole key'},
    "key.offline": {"pt": 'Sem resposta do serviço (internet?) {detail}', "en": 'No answer from the service (internet?) {detail}'},
    "opt.check_updates": {"pt": 'Avisar quando houver uma versão nova', "en": 'Tell me when a new version is out'},
    "opt.check_updates_d": {"pt": 'Ao abrir, pergunta ao GitHub qual é a última versão (sem enviar dados teus).', "en": 'On start-up, asks GitHub for the latest version (no data of yours is sent).'},
    "upd.available": {"pt": 'Há uma versão nova do Cratekeeper: {v}', "en": 'A new Cratekeeper version is available: {v}'},
    "upd.install": {"pt": 'Atualizar', "en": 'Update'},
    "upd.open_page": {"pt": 'Ver no GitHub', "en": 'Open on GitHub'},
    "upd.later": {"pt": 'Mais tarde', "en": 'Later'},
    "upd.downloading": {"pt": 'A descarregar… {pct}%', "en": 'Downloading… {pct}%'},
    "upd.busy": {"pt": 'Espera que a organização termine antes de atualizar.', "en": 'Wait for the current run to finish before updating.'},
    "upd.failed": {"pt": 'Não foi possível descarregar a atualização. Abri a página para a descarregares à mão.', "en": 'Could not download the update. I opened the page so you can download it yourself.'},
    "shut.toggle": {"pt": 'Desligar o PC no fim', "en": 'Shut down the PC when done'},
    "shut.tip": {"pt": 'Quando o Organizar terminar, o Windows desliga-se (fecha as outras apps sem perguntar). 60 s para cancelar.', "en": 'When Organize finishes, Windows shuts down (other apps are closed without asking). 60 s to cancel.'},
    "shut.confirm": {"pt": 'No fim da organização o PC desliga-se e fecha as outras apps sem perguntar — trabalho não guardado nelas perde-se.\n\nAtivar?', "en": 'When the run ends the PC shuts down and closes other apps without asking — unsaved work in them is lost.\n\nTurn on?'},
    "shut.countdown": {"pt": 'Organização terminada. O PC desliga-se em {s} s.', "en": 'Done. The PC shuts down in {s} s.'},
    "shut.cancel": {"pt": 'Cancelar e não desligar', "en": 'Cancel, keep it on'},
    "shut.cancelled": {"pt": 'Encerramento do PC cancelado.', "en": 'PC shutdown cancelled.'},
    "shut.windows_msg": {"pt": 'Cratekeeper: organização terminada, o PC vai desligar.', "en": 'Cratekeeper: done, the PC will shut down.'},
    "btn.close": {"pt": "Fechar", "en": "Close"},
    # status
    "status.ready": {"pt": "Pronto.", "en": "Ready."},
    "status.starting": {"pt": "A começar…", "en": "Starting…"},
    "status.cancelling": {"pt": "A cancelar… (termina o ficheiro atual)", "en": "Cancelling… (finishing the current file)"},
    "status.preview_done": {"pt": "Pré-visualização pronta — nada foi alterado.", "en": "Preview ready — nothing was changed."},
    "status.done": {"pt": "Feito.", "en": "Done."},
    "status.stopped": {"pt": "Parado.", "en": "Stopped."},
    "card.progress": {"pt": "Progresso", "en": "Progress"},
    "card.summary": {"pt": "Resumo", "en": "Summary"},
    "log.placeholder": {"pt": "Os detalhes de cada execução aparecem aqui.", "en": "Details of each run show up here."},
    "state.waiting": {"pt": "", "en": ""},
    "state.running": {"pt": "a correr", "en": "running"},
    "state.done": {"pt": "feito", "en": "done"},
    "state.off": {"pt": "desligado", "en": "off"},
    "state.error": {"pt": "parado", "en": "stopped"},
    # dialogs
    "msg.pick_folder": {"pt": "Escolhe a pasta das músicas.", "en": "Choose your music folder."},
    "msg.run_confirm": {"pt": "Vai mover e renomear ficheiros em:\n{root}\n\nO rekordbox / Serato tem de estar fechado. "
                              "No fim faz 'Relocate' nele.\n\nContinuar?",
                        "en": "This will move and rename files in:\n{root}\n\nrekordbox / Serato must be closed. "
                              "Afterwards, use 'Relocate' in it.\n\nContinue?"},
    "msg.undo_confirm": {"pt": 'Desfazer a última execução?\nAs faixas voltam ao sítio, o que foi para a quarentena regressa e as tags originais são repostas.', "en": 'Undo the last run?\nFiles go back where they were, quarantined files return and the original tags are restored.'},
    "msg.close_running": {"pt": "Ainda está a trabalhar. Cancelar e fechar quando terminar o ficheiro atual?",
                          "en": "Still working. Cancel and close once the current file is done?"},
    "msg.cancelled": {"pt": "Cancelado. O que já foi feito fica feito e pode ser desfeito.",
                      "en": "Cancelled. What was already done stays done and can be undone."},
    "log.kind.preview": {"pt": "Pré-visualizar", "en": "Preview"},
    "log.kind.run": {"pt": "Organizar", "en": "Organize"},
    "log.kind.undo": {"pt": "Desfazer", "en": "Undo"},
    "log.warnings": {"pt": "Avisos ({n}):", "en": "Warnings ({n}):"},
    "log.rekordbox": {"pt": "No rekordbox: Ficheiro › Gerir faixas inexistentes › Auto Relocate; depois Recarregar tag.",
                      "en": "In rekordbox: File › Manage Missing Files › Auto Relocate; then Reload Tag."},
    "stat.tracks": {"pt": "faixas", "en": "tracks"},
    "stat.moved": {"pt": "movidas", "en": "moved"},
    "stat.dups": {"pt": "repetidas", "en": "duplicates"},
    "stat.online": {"pt": "géneros online", "en": "online genres"},
    "stat.tags": {"pt": "tags corrigidas", "en": "tags fixed"},
    # pipeline steps (progress)
    "step.extract": {"pt": "Extrair packs", "en": "Extracting packs"},
    "step.organize": {"pt": "Arrumar por género", "en": "Sorting by genre"},
    "step.dedupe_scan": {"pt": "Procurar repetidas", "en": "Finding duplicates"},
    "step.dedupe_remove": {"pt": "Remover repetidas", "en": "Removing duplicates"},
    "step.online": {"pt": "Procurar género online", "en": "Looking up genres online"},
    "step.bpm": {"pt": "Separar por BPM", "en": "Splitting by BPM"},
    "step.tags": {"pt": "Corrigir tags", "en": "Fixing tags"},
    "step.preview": {"pt": "Pré-visualizar", "en": "Previewing"},
    "step.undo": {"pt": "Desfazer", "en": "Undoing"},
    # report
    "rep.archives_extracted": {"pt": "compactados extraídos", "en": "archives extracted"},
    "rep.archives_trashed": {"pt": 'compactados para a quarentena', "en": 'archives moved to quarantine'},
    "rep.moved": {"pt": "movidas para {x}", "en": "moved to {x}"},
    "rep.junk_trashed": {"pt": 'ficheiros que não são música para a quarentena', "en": 'non-music files moved to quarantine'},
    "rep.dups_trashed": {"pt": 'repetidas para a quarentena', "en": 'duplicates moved to quarantine'},
    "rep.online": {"pt": "género encontrado online ({x})", "en": "genre found online ({x})"},
    "rep.bpm_sorted": {"pt": "separadas por BPM", "en": "split by BPM"},
    "rep.sites_cleaned": {"pt": "faixas sem sites nas tags", "en": "tracks with sites removed from tags"},
    "rep.genre_spam_cleared": {"pt": "géneros com site apagados", "en": "genre tags with a site cleared"},
    "rep.genre_tag_fixed": {"pt": "géneros corrigidos na tag", "en": "genre tags fixed"},
    "rep.archives_pending": {"pt": "compactados por extrair", "en": "archives to extract"},
    "rep.to_move": {"pt": "a mover para {x}", "en": "to move to {x}"},
    "rep.unreadable": {"pt": "faixas com tags estragadas (ficam onde estão)", "en": "tracks with damaged tags (left in place)"},
    "rep.tracks": {"pt": "faixas", "en": "tracks"},
    "rep.dups_pending": {"pt": "repetidas a remover", "en": "duplicates to remove"},
    "rep.undo_returned": {"pt": "faixas devolvidas", "en": "files moved back"},
    "rep.undo_tags": {"pt": "faixas com as tags originais repostas", "en": "tracks with original tags restored"},
    "rep.undo_from_quarantine": {"pt": "faixas recuperadas da quarentena", "en": "files brought back from quarantine"},
    "rep.purged": {"pt": "execuções da quarentena enviadas para a Reciclagem", "en": "quarantined runs sent to the Recycle Bin"},
    "rep.undo_in_trash": {"pt": "na Reciclagem (restaurar pelo Windows)", "en": "in the Recycle Bin (restore from Windows)"},
    "rep.undo_nothing": {"pt": "nada para desfazer", "en": "nothing to undo"},
    # errors
    "err.no_folder": {"pt": "Pasta não existe: {root}", "en": "Folder does not exist: {root}"},
    "err.need_7zip": {"pt": "precisa do 7-Zip instalado para .rar/.7z (7-zip.org)", "en": "needs 7-Zip installed for .rar/.7z (7-zip.org)"},
    "err.too_broad": {"pt": "Pasta demasiado geral: {root}. Escolhe a pasta das músicas (ex.: D:\\musica), não o disco nem a pasta do utilizador.",
                      "en": "Folder too broad: {root}. Choose your music folder (e.g. D:\\Music), not a whole drive or your user folder."},
    "err.undo_missing": {"pt": "não encontrado (não devolvido): {path}", "en": "not found (not moved back): {path}"},
    "err.undo_conflict": {"pt": "já existe outro ficheiro no sítio original (não devolvido): {path}",
                          "en": "another file is already at the original place (not moved back): {path}"},
    "err.archive_many": {"pt": "demasiados ficheiros no pack ({n}) — não extraído", "en": "too many files in the archive ({n}) — not extracted"},
    "err.archive_bomb": {"pt": "pack suspeito (compressão exagerada) — não extraído", "en": "suspicious archive (extreme compression) — not extracted"},
    "err.no_space": {"pt": "sem espaço no disco para extrair ({gb} GB)", "en": "not enough disk space to extract ({gb} GB)"},
    "err.busy": {"pt": "Esta biblioteca já está a ser organizada noutra janela do Cratekeeper.",
                 "en": "This library is already being organized in another Cratekeeper window."},
    "err.crash": {"pt": "Ocorreu um erro inesperado. Os detalhes ficaram em:\n{path}",
                  "en": "An unexpected error occurred. Details were saved to:\n{path}"},
    "err.unreadable": {"pt": "tags estragadas, ficou onde estava: {path}", "en": "damaged tags, left where it was: {path}"},
    "rep.undo_extract": {"pt": 'packs extraídos desfeitos', "en": 'extracted packs undone'},
    "rep.tags_pending": {"pt": 'faixas com o género da tag a corrigir', "en": 'tracks whose genre tag will be fixed'},
    "rep.bpm_pending": {"pt": 'faixas sem género a separar por BPM', "en": 'tracks without genre to split by BPM'},
    "rep.online_pending": {"pt": 'faixas sem género a procurar online', "en": 'tracks without genre to look up online'},
    "rep.junk_pending": {"pt": 'ficheiros que não são música nos packs', "en": 'non-music files in the packs'},
    "log.preview_limits": {"pt": 'Não incluído na pré-visualização: faixas ainda dentro dos packs, resultados da procura online e limpeza de sites nas tags.', "en": 'Not in the preview: tracks still inside packs, online lookup results and site cleaning in tags.'},
    "err.archive_list": {"pt": 'não foi possível ver o conteúdo do pack — não extraído', "en": 'could not list the archive contents — not extracted'},
    "err.tag_check": {"pt": 'a gravação das tags não passou na verificação — ficheiro original mantido', "en": 'the tag save failed verification — original file kept'},
    "err.online_skipped": {"pt": "Procura online saltada: sem chaves do Discogs/Last.fm e MusicBrainz desligado.",
                           "en": "Online lookup skipped: no Discogs/Last.fm keys and MusicBrainz is off."},
    # terms
    "terms.title": {"pt": "Termos e Condições", "en": "Terms and Conditions"},
    "terms.intro": {"pt": "Antes de usar, lê e aceita os termos.", "en": "Before using the app, please read and accept the terms."},
    "terms.check": {"pt": "Li e aceito os Termos e Condições", "en": "I have read and accept the Terms and Conditions"},
    "terms.accept": {"pt": "Aceitar e continuar", "en": "Accept and continue"},
    "terms.exit": {"pt": "Sair", "en": "Exit"},
    "terms.menu": {"pt": "Termos", "en": "Terms"},
}
