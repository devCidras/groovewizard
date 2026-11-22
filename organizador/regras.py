"""Genre rules: tag aliases, pack-name rules, online-tag rules and parent folders.

Folder names are the canonical genres (mostly Beatport's). Edit freely.
"""

NO_GENRE = "Sem Genero"
OTHER = "Outros"

# canonical genre -> tag spellings that mean the same thing (compared after .title())
_GROUPS = {
    "Drum & Bass": ["Drum And Bass", "Drum N Bass", "Dnb", "Jungle"],
    "Hard Groove": ["Hardgroove", "Techno-Hardgroove", "Techno - Hardgroove"],
    "Techno": ["#Deep #Industrial #Techno", "Electronica-Deep Techno", "Ambient Techno", "Acid", "Psy-Techno"],
    "Techno (Raw - Deep - Hypnotic)": ["Techno (Raw", "Raw", "Techno (Raw - Deep - Hypnotic) - Dub",
                                       "Techno ((Raw - Deep - Hypnotic)", "Dark Techno", "Deep - Hypnotic", "Hypnotic Techno"],
    "Techno (Peak Time - Driving)": ["Techno (Peak Time - Driving) - Peak Time", "Driving"],
    "Hard Techno": ["Hard Techno-Schranz", "Hardtechno", "Schranz", "Techno-Schranz", "Industrial", "Industrial Techno"],
    "Techno House": ["Techno-House"],
    "Melodic House & Techno": ["Melodic House", "Melodic Techno", "Melodic House & Techno - Melodic House"],
    "House": ["Dance - House", "Afro House", "Latin House", "Jackin House", "Jackin' House", "French House", "Disco",
              "Dark Disco", "Tribal", "Funky-Vocal-Disco-Club House", "Organic House - Downtempo", "Electro Techno-House",
              "Electro-Techno-House-Dance", "Afro House - Afro Melodic", "Afro House - Afro - Latin", "Afro Melodic",
              "Afro - Latin", "Amapiano"],
    "Tech House": ["Tech House - Latin Tech", "Groovy Minimal Tech House", "House Tech", "Latin Tech", "Tech"],
    "Deep House": ["House Deep"],
    "Progressive House": ["House Progressive"],
    "Trance": ["Trance (Main Floor)", "Trance (Raw - Deep - Hypnotic)", "Psy-Trance", "Trance Modern"],
    "Electro": ["Electro (Classic - Detroit - Modern)"],
    "Indie Dance": ["Indie Dance - Dark Disco"],
    "Electronica - Downtempo": ["Electronica", "Downtempo", "Ambient - Experimental", "Psychill", "Chill"],
    "Breaks - Breakbeat - Uk Bass": ["Bass - Club"],
    "Bass House": ["Bass House Weirdo Cool"],
    "Minimal - Deep Tech": ["Minimal", "Deep Tech", "Minimal-Deep Tech", "Minimal House", "Minimal Techno",
                            "Minimal-Tech House", "Minimal - Deep Tech - Minimal House"],
    "Uk Garage": ["Uk Garage - Bassline", "Future Garage"],
    "Dance": ["Dance - Pop", "Dance-Pop", "Dance - Electro Pop", "Edm", "Dance - Electronic", "Electro House"],
    # genres with too few tracks for their own folder
    OTHER: ["Pop", "Alternative Rock", "Klassiek", "Dub", "Hardstyle", "Pop Rock", "Tek", "Hard Dance - Hardcore - Neo Rave",
            "Dj Tools - Acapellas", "Hip-Hop-Rap", "Brazilian Funk", "Contemporary Christian", "Hard Rock", "Classical",
            "K-Pop", "Trap - Future Bass", "Funk - Soul", "Blues", "Halftime"],
}
# tags that say nothing about the style: treated as "no genre" so the online lookup tries
_GENERIC = ["Unknown", "Other", "Various", "Club", "Electronic", "Compilation Electronic", "Compilation Electronica",
            "Électronique", "Электронная Музыка", "Танцевальная Музыка"]
ALIAS = {**{g: "" for g in _GENERIC}, **{s: g for g, subs in _GROUPS.items() for s in subs}}

# Untagged files: genre from the pack/folder name they came from. Order matters: most specific first.
FOLDER_RULES = [
    (r"raw[\W_]+deep|techno_raw|\(r h\)|\(r_d_h\)", "Techno (Raw - Deep - Hypnotic)"),
    (r"melodic house|melodic h&t", "Melodic House & Techno"),
    (r"indie tech", "Indie Tech"),
    (r"\(p_d\)|peak time|driving techno", "Techno (Peak Time - Driving)"),
    (r"hard ?groove", "Hard Groove"),
    (r"hard techno", "Hard Techno"),
    (r"tech[ _]house", "Tech House"),
    (r"minimal", "Minimal - Deep Tech"),
    (r"deep house", "Deep House"),
    (r"afro house|best new house|picks house", "House"),
    (r"progressive house", "Progressive House"),
    (r"dubstep", "Dubstep"),
    (r"drum ?(&|and|n) ?bass|\bdnb\b", "Drum & Bass"),
    (r"classics techno|best of techno", "Techno"),
]

# Online tags (Discogs styles, MusicBrainz/Last.fm tags) -> folder. Substring match, order = priority on ties.
ONLINE_RULES = [
    ("hardgroove", "Hard Groove"), ("hard groove", "Hard Groove"),
    ("hard techno", "Hard Techno"), ("industrial techno", "Hard Techno"), ("schranz", "Hard Techno"),
    ("hypnotic", "Techno (Raw - Deep - Hypnotic)"), ("dub techno", "Techno (Raw - Deep - Hypnotic)"),
    ("deep techno", "Techno (Raw - Deep - Hypnotic)"), ("raw techno", "Techno (Raw - Deep - Hypnotic)"),
    ("peak time", "Techno (Peak Time - Driving)"), ("driving", "Techno (Peak Time - Driving)"),
    ("melodic techno", "Melodic House & Techno"), ("melodic house", "Melodic House & Techno"),
    ("tech house", "Tech House"), ("minimal", "Minimal - Deep Tech"), ("microhouse", "Minimal - Deep Tech"),
    ("progressive house", "Progressive House"), ("trance", "Trance"),
    ("organic house", "Organic House"), ("indie dance", "Indie Dance"), ("nu disco", "Nu Disco - Disco"),
    ("indie tech", "Indie Tech"), ("breakbeat", "Breaks - Breakbeat - Uk Bass"), ("breaks", "Breaks - Breakbeat - Uk Bass"),
    ("drum and bass", "Drum & Bass"), ("drum n bass", "Drum & Bass"), ("jungle", "Drum & Bass"),
    ("downtempo", "Electronica - Downtempo"), ("ambient", "Electronica - Downtempo"),
    ("deep house", "Deep House"), ("bass house", "Bass House"),
    ("uk garage", "Uk Garage"), ("bassline", "Uk Garage"), ("dubstep", "Dubstep"), ("riddim", "Dubstep"),
    ("electro house", "Dance"), ("electro", "Electro"), ("acid house", "House"), ("acid", "Techno"), ("techno", "Techno"),
    ("house", "House"), ("disco", "House"), ("dance", "Dance"), ("edm", "Dance"),
]

# Parent folders, so the library root is not a wall of 30 folders. Genres not listed stay at the root.
FAMILIES = {
    "House": ["House", "Tech House", "Deep House", "Progressive House", "Organic House", "Funky House",
              "Bass House", "Nu Disco - Disco", "Minimal - Deep Tech", "Techno House"],
    "Techno": ["Techno", "Techno (Peak Time - Driving)", "Techno (Raw - Deep - Hypnotic)", "Hard Techno", "Hard Groove"],
    "Melodic & Indie": ["Melodic House & Techno", "Indie Dance", "Indie Tech"],
    "Bass & Breaks": ["Drum & Bass", "Dubstep", "Breaks - Breakbeat - Uk Bass", "Uk Garage"],
    "Dance & Mainstage": ["Dance", "Mainstage", "Electro", "Trance"],
}
FAMILY_OF = {g: fam for fam, subs in FAMILIES.items() for g in subs}

# NO_GENRE / OTHER above are internal ids. On disk they get a name in the language chosen on first use
# (fixed afterwards, so switching the UI language never renames folders).
BPM_LIMITS = [115, 122, 128, 135, 999]  # upper bound, exclusive
FOLDER_NAMES = {
    "pt": {NO_GENRE: "Sem Genero", OTHER: "Outros",
           "bpm": ["BPM menos de 115", "BPM 115-122", "BPM 122-128", "BPM 128-135", "BPM 135+"], "bpm_unknown": "BPM desconhecido"},
    "en": {NO_GENRE: "No Genre", OTHER: "Other",
           "bpm": ["BPM under 115", "BPM 115-122", "BPM 122-128", "BPM 128-135", "BPM 135+"], "bpm_unknown": "BPM unknown"},
}
