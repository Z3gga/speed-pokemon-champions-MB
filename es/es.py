import json
import os
import re
import difflib
import unicodedata
import reflex as rx
import pandas as pd
from typing import List, Dict, Optional, Tuple, TypedDict

# Rutas de los íconos de botón (Scarf/PAR/Mega). Van en assets/icons/ y
# Reflex los sirve como estáticos en /icons/<archivo>. Nombres tal cual los
# subió el usuario.
ICON_SCARF = "/icons/cho.png"
ICON_PAR = "/icons/par.png"
ICON_MEGA = "/icons/meg.png"
ICON_ABILITY = "/icons/ability.png"

TEAM_SIZE = 6

# ---------------------------------------------------------------------------
# Historial de matchups: CADA VEZ que se guarda un matchup (botón "Save
# matchup" -> Victoria/Derrota) se agrega una fila a este Excel con los 6
# Pokémon propios, los 6 rivales y el resultado. Vive en `data/`, fuera de
# `assets/` a propósito -- lo que hay en `assets/` Reflex lo sirve como
# estático (descargable por cualquiera que entre a la app), y este archivo
# puede ir acumulando muchas partidas que uno no necesariamente quiere
# público. Por ahora es solo un registro (se usará más adelante para
# estadísticas); la carpeta se crea sola la primera vez que se guarda algo.
# ---------------------------------------------------------------------------
MATCHUP_LOG_DIR = "data"
MATCHUP_LOG_PATH = os.path.join(MATCHUP_LOG_DIR, "matchup_history.xlsx")
MATCHUP_LOG_MY_COLS = [f"Mi Pokémon {i + 1}" for i in range(TEAM_SIZE)]
MATCHUP_LOG_RIVAL_COLS = [f"Rival Pokémon {i + 1}" for i in range(TEAM_SIZE)]
MATCHUP_LOG_COLUMNS = ["Fecha", *MATCHUP_LOG_MY_COLS, *MATCHUP_LOG_RIVAL_COLS, "Resultado"]


def _append_matchup_result(my_team: List[str], rival_team: List[str], result: str) -> Optional[str]:
    """
    Agrega una fila al Excel de historial (`MATCHUP_LOG_PATH`): fecha,
    los 6 Pokémon propios, los 6 rivales, y el resultado ("Victoria" /
    "Derrota"). Si el archivo no existe todavía lo crea con el
    encabezado; si ya existe, lee lo que había y le suma la fila nueva
    (requiere `openpyxl` instalado, que es lo que pandas usa para leer/
    escribir .xlsx). Devuelve un mensaje de error si algo falla (para
    mostrarlo en el diálogo) o `None` si se guardó bien.
    """
    try:
        os.makedirs(MATCHUP_LOG_DIR, exist_ok=True)
        row = {
            "Fecha": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
            **{col: my_team[i] for i, col in enumerate(MATCHUP_LOG_MY_COLS)},
            **{col: rival_team[i] for i, col in enumerate(MATCHUP_LOG_RIVAL_COLS)},
            "Resultado": result,
        }
        if os.path.exists(MATCHUP_LOG_PATH):
            existing = pd.read_excel(MATCHUP_LOG_PATH, engine="openpyxl")
            df = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
        else:
            df = pd.DataFrame([row], columns=MATCHUP_LOG_COLUMNS)
        df.to_excel(MATCHUP_LOG_PATH, index=False, engine="openpyxl")
        return None
    except Exception as e:
        print(f"[PokemonState] No se pudo guardar el historial de matchups: {e!r}")
        return f"No se pudo guardar el matchup: {e}"


def _read_matchup_history() -> Tuple[List[str], Optional[str]]:
    """
    Lee `MATCHUP_LOG_PATH` y arma una lista de líneas de texto (una por
    fila, más reciente primero) lista para mostrar en el diálogo de
    historial. Se arman como texto ya formateado en vez de mandar el
    Dict crudo al frontend porque las columnas tienen espacios/tildes
    ("Mi Pokémon 1") y eso complica innecesariamente el indexado de Vars
    del lado de React; total, para este historial solo hace falta
    mostrarlo, no operar sobre columnas individuales en la UI.
    Devuelve `(líneas, error_o_None)`.
    """
    if not os.path.exists(MATCHUP_LOG_PATH):
        return [], None
    try:
        df = pd.read_excel(MATCHUP_LOG_PATH, engine="openpyxl")
        rows: List[str] = []
        for _, r in df.iterrows():
            my_names = ", ".join(str(r.get(col, "")) for col in MATCHUP_LOG_MY_COLS)
            rival_names = ", ".join(str(r.get(col, "")) for col in MATCHUP_LOG_RIVAL_COLS)
            fecha = str(r.get("Fecha", ""))
            resultado = str(r.get("Resultado", ""))
            rows.append(f"{fecha} · {resultado} · Vos: {my_names} · Rival: {rival_names}")
        rows.reverse()
        return rows, None
    except Exception as e:
        print(f"[PokemonState] No se pudo leer el historial de matchups: {e!r}")
        return [], f"No se pudo leer el historial: {e}"



# Parámetros fijos del formato (Pokémon Champions): Nivel 50, IVs de Speed al
# tope (31). Los EVs en este formato van directo de 0 a 32 (no 0-252 como en
# el formato clásico), cada punto suma 1 al cálculo sin dividir entre 4.
SPEED_LEVEL = 50
SPEED_IV = 31
SPEED_EV_MAX = 32

# Estilo de panel translúcido ("glass") reutilizado en las cajas de la UI
# para que el texto siga siendo legible arriba del fondo.jpeg. Blur +
# fondo semitransparente oscuro, con un borde sutil.
PANEL_STYLE = {
    "background": "rgba(20, 14, 32, 0.55)",
    "backdrop-filter": "blur(10px)",
    "-webkit-backdrop-filter": "blur(10px)",
    "border": "1px solid rgba(255, 255, 255, 0.12)",
    "border-radius": "12px",
    "padding": "1.25em",
}

# Variantes de PANEL_STYLE para diferenciar visualmente el panel propio del
# rival: mismo blur/borde/padding, solo cambia el color de fondo (rgba).
MY_PANEL_STYLE = {
    **PANEL_STYLE,
    "background": "rgba(30, 40, 100, 0.55)",      # azul
    "border": "2px solid rgba(20, 23, 71, 1)",
    "width": "336px",
}
RIVAL_PANEL_STYLE = {
    **PANEL_STYLE,
    "background": "rgba(120, 20, 70, 0.55)",      # rosa
    "border": "2px solid rgba(20, 23, 71, 1)",
    "width": "336px",
}

# Mismos colores que MY_PANEL_STYLE / RIVAL_PANEL_STYLE pero SIN el ancho
# fijo -- estas son para las tarjetas de stats de "Tu equipo" (columna
# derecha), que deben mantener su tamaño auto dentro del grid en vez de
# heredar el ancho fijo pensado para los cuadros chicos de la izquierda.
MY_CARD_STYLE = {k: v for k, v in MY_PANEL_STYLE.items() if k != "width"}
RIVAL_CARD_STYLE = {k: v for k, v in RIVAL_PANEL_STYLE.items() if k != "width"}

# ---------------------------------------------------------------------------
# Fondo de la PÁGINA (no de los paneles) en sus dos variantes, oscuro y
# claro. El toggle de tema (esquina inferior derecha) solo cambia esto --
# a propósito no toca PANEL_STYLE/MY_PANEL_STYLE/RIVAL_PANEL_STYLE, para
# que los paneles se vean igual en los dos modos.
# ---------------------------------------------------------------------------
_POKEBALL_SVG_TEMPLATE = (
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "viewBox='0 0 400 400'%3E%3Ccircle cx='200' cy='200' r='170' "
    "fill='none' stroke='{stroke}' stroke-width='3'/%3E"
    "%3Cline x1='30' y1='200' x2='150' y2='200' "
    "stroke='{stroke}' stroke-width='3'/%3E"
    "%3Cline x1='250' y1='200' x2='370' y2='200' "
    "stroke='{stroke}' stroke-width='3'/%3E"
    "%3Ccircle cx='200' cy='200' r='38' fill='none' "
    "stroke='{stroke}' stroke-width='3'/%3E"
    "%3Ccircle cx='200' cy='200' r='16' fill='none' "
    "stroke='{stroke}' stroke-width='3'/%3E%3C/svg%3E\")"
)

PAGE_BACKGROUND_DARK = (
    "radial-gradient(ellipse at 25% 15%, rgba(52, 40, 100, 0.55) 0%, "
    "rgba(8, 8, 18, 0.97) 55%), "
    "linear-gradient(165deg, #0a0a16 0%, #130f28 45%, #180d2a 100%)"
)
PAGE_BACKGROUND_IMAGE_DARK = _POKEBALL_SVG_TEMPLATE.format(stroke="rgba(255,255,255,0.05)")

PAGE_BACKGROUND_LIGHT = (
    "radial-gradient(ellipse at 25% 15%, rgba(255, 255, 255, 0.9) 0%, "
    "rgba(221, 216, 238, 0.97) 55%), "
    "linear-gradient(165deg, #f6f4fb 0%, #ece7f7 45%, #e4ddf3 100%)"
)
PAGE_BACKGROUND_IMAGE_LIGHT = _POKEBALL_SVG_TEMPLATE.format(stroke="rgba(20,14,32,0.055)")

# `background` (shorthand) y `background-image` (longhand) NO se combinan en
# capas si se declaran como props separadas -- la segunda pisa por completo
# a la primera. Por eso antes el toggle "no cambiaba nada": ganaba siempre
# `background_image` (la pokebola) y el gradiente de color nunca se pintaba.
# Acá se arma UNA sola lista de capas (pokebola arriba, gradientes abajo)
# para usar en una única prop `background_image`.
PAGE_BACKGROUND_LAYERS_DARK = f"{PAGE_BACKGROUND_IMAGE_DARK}, {PAGE_BACKGROUND_DARK}"
PAGE_BACKGROUND_LAYERS_LIGHT = f"{PAGE_BACKGROUND_IMAGE_LIGHT}, {PAGE_BACKGROUND_LIGHT}"


class SlotInfo(TypedDict):
    """
    Tipo explícito para cada slot activo. Antes se usaba `Dict[str, str]`
    para todo, lo que hacía que Reflex asumiera que TODOS los valores del
    dict eran strings — incluido `global_index`, que en realidad es un
    int. Eso rompía cualquier indexado como `PokemonState.scarf[idx]`
    (esperaba un int y recibía algo tipado como string). Con TypedDict,
    cada campo conserva su tipo real.
    """
    global_index: int
    side: str
    name: str


class TeamSlotSnapshot(TypedDict):
    """
    Todo lo necesario para reconstruir UN slot guardado (de un equipo
    propio o de un matchup completo): la especie más su config de Speed
    entera (EVs, naturaleza, Scarf/PAR/Ability/Mega). Se usa como la
    unidad básica tanto de "Guardar equipo" como de "Save matchup" -- un
    equipo guardado es una lista de 6 de estos, un matchup guardado son
    2 listas (mía + rival).
    """
    species: str
    speed_ev: int
    nature: str
    scarf: bool
    para: bool
    ability_active: bool
    mega_active: bool
    mega_choice: int


def _empty_slot_snapshot() -> TeamSlotSnapshot:
    return {
        "species": "", "speed_ev": 0, "nature": "", "scarf": False,
        "para": False, "ability_active": False, "mega_active": False,
        "mega_choice": 0,
    }


# ---------------------------------------------------------------------------
# Carga del CSV UNA SOLA VEZ a nivel de módulo (I/O de disco cacheado, no
# dentro de un @rx.var que se recalcularía en cada render).
#
# `assets/pokemon.csv` se dejó de usar: ahora `speed_tiers_regb.csv` es la
# ÚNICA fuente de datos del roster (nombre, Base Speed y Ability). El sprite
# de cada Pokémon sale de `assets/referencias/<Nombre>.webp`, con el nombre
# EXACTO (con espacios y tildes) tal como aparece en ese CSV -- no hace
# falta ningún mapeo aparte, Reflex sirve todo lo de `assets/` como estático.
# ---------------------------------------------------------------------------
SPEED_TIERS_PATH = "assets/speed_tiers_regb.csv"
REFERENCIAS_DIR = "/referencias"  # sirve assets/referencias/


def _fix_mojibake(value: str) -> str:
    """
    `speed_tiers_regb.csv` viene con un bug de doble-encoding UTF-8: 'é'
    quedó guardado como los bytes de 'Ã©'. Este round-trip (decodificar
    como si fuera Latin-1 y volver a interpretar como UTF-8) lo revierte.
    Si el valor no está mojibake-encoded (o no es texto), lo devuelve tal
    cual en vez de romper.
    """
    try:
        return value.encode("latin1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError, AttributeError):
        return value


def _load_pokemon_data() -> List[Dict]:
    """
    Carga nombre + Base Speed + Ability + MegaEvolve + ruta de imagen del
    roster COMPLETO, todo desde `speed_tiers_regb.csv` (formato: `#,
    Pokémon, Base, No Invest, Max+, Max, Min, Scarf/+1, Tailwind/+2,
    Paralyzed, Ability, MegaEvolve`).

    La columna de nombre se referencia por posición (`df.columns[1]`) y no
    por su string literal, porque ese string llega mojibake-encoded
    ("PokÃ©mon") y depender de él sería frágil. `Ability` y `MegaEvolve` sí
    se referencian por nombre literal porque no tienen tildes, y ambas son
    opcionales.

    Las formas Mega son FILAS PROPIAS del roster (con su propio nombre,
    Base Speed, sprite, etc.). `MegaEvolve` vale `"No"` para la mayoría, y
    para las filas de Mega trae el NOMBRE del Pokémon base del que
    evoluciona (ej. la fila "Mega Alakazam" tiene `MegaEvolve = "Alakazam"`).
    Eso es lo que se usa para armar la conexión base -> mega más abajo.
    """
    try:
        df = pd.read_csv(SPEED_TIERS_PATH, encoding="utf-8-sig")
        name_col = df.columns[1]
        has_ability_col = "Ability" in df.columns
        has_mega_col = "MegaEvolve" in df.columns
        data: List[Dict] = []
        for _, row in df.iterrows():
            name = _fix_mojibake(str(row[name_col])).strip()
            try:
                base = int(row["Base"])
            except (ValueError, TypeError, KeyError):
                print(
                    f"[PokemonState] Fila inválida en {SPEED_TIERS_PATH} "
                    f"para {name!r}: no se pudo leer 'Base' -> se omite"
                )
                continue
            ability = ""
            if has_ability_col and pd.notna(row["Ability"]):
                ability = str(row["Ability"]).strip()
            mega_evolve_from = ""
            mega_capable = False
            if has_mega_col and pd.notna(row["MegaEvolve"]):
                raw = str(row["MegaEvolve"]).strip()
                raw_lower = raw.lower()
                if raw_lower == "yes":
                    # Esta fila es un Pokémon BASE que sí megaevoluciona
                    # (su Mega está en otra fila). Es lo único que debe
                    # aparecer en el selector de equipo.
                    mega_capable = True
                elif raw and raw_lower != "no":
                    # Esta fila ES la Mega -- el valor es el nombre del
                    # Pokémon base del que evoluciona.
                    mega_evolve_from = raw
            data.append(
                {
                    "name": name,
                    "base": base,
                    "ability": ability,
                    "mega_evolve_from": mega_evolve_from,
                    "mega_capable": mega_capable,
                    "image": f"{REFERENCIAS_DIR}/{name}.webp",
                }
            )
        return data
    except Exception as e:
        print(f"[PokemonState] No se pudo cargar {SPEED_TIERS_PATH}: {e!r}")
        return [
            {
                "name": "Carga tu CSV en " + SPEED_TIERS_PATH,
                "base": 0, "ability": "", "mega_evolve_from": "",
                "mega_capable": False, "image": "",
            },
        ]


POKEMON_DATA = _load_pokemon_data()
POKEMON_NAMES = [p["name"] for p in POKEMON_DATA]
# Lista para el SELECTOR de equipo: todos los Pokémon BASE del roster,
# tengan o no Mega (columna MegaEvolve en "Yes" o en "No"). Lo único que
# se excluye son las filas que SON una Mega (`mega_evolve_from` cargado,
# ej. "Mega Swampert"), porque esas no se eligen directamente -- entran
# al equipo como su forma base y se megaevolucionan después con el botón.
# Esas filas de Mega siguen necesitándose para el resto de la lógica
# (sprite, Base Speed, habilidad, el cruce base->mega).
TEAM_SELECTOR_NAMES: List[str] = [p["name"] for p in POKEMON_DATA if not p["mega_evolve_from"]]
# Mapa nombre -> ruta de sprite (assets/referencias/<nombre>.webp)
POKEMON_IMAGES: Dict[str, str] = {p["name"]: p["image"] for p in POKEMON_DATA}
# Mapa nombre -> Base Speed
POKEMON_BASE_SPEED: Dict[str, int] = {p["name"]: p["base"] for p in POKEMON_DATA}
# Mapa nombre -> habilidad relevante para Speed ("" si no tiene ninguna).
# Determina si ese Pokémon muestra el botón de habilidad en la UI.
POKEMON_ABILITY: Dict[str, str] = {p["name"]: p["ability"] for p in POKEMON_DATA}

# Mapa nombre-de-la-Mega -> nombre-del-Pokémon-base, tal como viene directo
# de la columna MegaEvolve (solo para las filas que SON una Mega).
POKEMON_MEGA_FROM: Dict[str, str] = {
    p["name"]: p["mega_evolve_from"] for p in POKEMON_DATA if p["mega_evolve_from"]
}
# Cruce inverso: nombre-del-Pokémon-base -> LISTA de nombres de sus Megas.
#
# BUG ORIGINAL: esto era un dict comprehension `{base: mega for mega, base
# in POKEMON_MEGA_FROM.items()}`, es decir un solo valor por base. Para
# Pokémon con UNA sola Mega no se notaba, pero para los que tienen DOS
# (ej. Charizard -> Mega Charizard X/Y, Raichu -> sus dos formas Mega) la
# segunda fila pisaba a la primera al construir el dict, así que solo
# quedaba registrada la última Mega leída del CSV y el botón "Megaevolucionar"
# nunca podía desplegar la otra. Ahora se guardan TODAS en una lista, en el
# mismo orden en que aparecen en el CSV.
POKEMON_MEGA_OF_BASE: Dict[str, List[str]] = {}
for _mega, _base in POKEMON_MEGA_FROM.items():
    POKEMON_MEGA_OF_BASE.setdefault(_base, []).append(_mega)
# Mapa nombre-base -> cantidad de Megas que tiene (0 si no megaevoluciona).
# Determina si ese Pokémon muestra el botón de Mega en la UI, y si además
# hace falta mostrar el selector para elegir CUÁL Mega (cuando son 2+).
POKEMON_MEGA_COUNT: Dict[str, int] = {
    base: len(megas) for base, megas in POKEMON_MEGA_OF_BASE.items()
}
_unmatched_mega_links = [
    mega for mega, base in POKEMON_MEGA_FROM.items() if base not in POKEMON_BASE_SPEED
]
if _unmatched_mega_links:
    print(
        f"[PokemonState] Aviso: {len(_unmatched_mega_links)} filas de Mega en "
        f"{SPEED_TIERS_PATH} cuyo MegaEvolve no matchea ningún Pokémon base "
        f"del roster (revisar nombres): {_unmatched_mega_links}"
    )


# ---------------------------------------------------------------------------
# Import desde formato Showdown ("Pokémon @ Item / Ability: X / Level: 50 /
# EVs: N Spe / Naturaleza Nature / - Movimiento / ..."). Solo nos interesan
# 3 datos de cada bloque: la especie (para matchear contra el roster y
# resolver si es una Mega), los EVs de Speed, y si la naturaleza sube/baja
# Speed -- todo lo demás (item, habilidad, movimientos, IVs, Tera Type,
# etc.) se ignora por completo.
# ---------------------------------------------------------------------------

# Solo las naturalezas que suben o bajan Speed importan acá; el resto
# (Adamant, Modest, Bold, Calm, etc., y las neutras) no tocan Speed, así
# que se tratan igual que no haber elegido ninguna.
NATURE_SPEED_EFFECT: Dict[str, str] = {
    "timid": "pos", "jolly": "pos", "hasty": "pos", "naive": "pos",
    "brave": "neg", "relaxed": "neg", "quiet": "neg", "sassy": "neg",
}


def _normalize_name(s: str) -> str:
    """
    Normaliza un nombre para matchear de forma tolerante: saca tildes y
    baja a minúsculas/espacios. A propósito NO toca paréntesis ni
    corchetes -- el CSV los usa con significado real (ej.
    "Tauros [Paldean Form (Aqua Breed)]"), así que borrarlos a lo bruto
    hacía colisionar los 3 breeds de Tauros en una sola clave. La
    limpieza de ruido específico de Showdown (el "(F)"/"(M)" que a veces
    agrega al final) se hace aparte, en `_strip_trailing_gender_marker`.
    """
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def _strip_trailing_gender_marker(s: str) -> str:
    """Saca el "(M)"/"(F)" que Showdown agrega al final de algunos
    nombres, a veces redundante con un sufijo "-F"/"-M" que ya trae el
    propio nombre (ej. "Basculegion-F (F)", "Meowstic-F (F)")."""
    return re.sub(r"\s*\((?:M|F)\)\s*$", "", s, flags=re.IGNORECASE).strip()


# Región de Showdown ("-Alola", "-Galar", ...) -> adjetivo tal como
# aparece en el CSV entre corchetes ("[Alolan Form]", ...).
_REGION_ADJECTIVE: Dict[str, str] = {
    "alola": "Alolan", "alolan": "Alolan",
    "galar": "Galarian", "galarian": "Galarian",
    "hisui": "Hisuian", "hisuian": "Hisuian",
    "paldea": "Paldean", "paldean": "Paldean",
}


def _build_form_candidates(raw: str) -> List[str]:
    """
    Traduce el formato de guiones de Showdown al formato de corchetes del
    CSV, para las familias de formas que cambian de convención entre uno
    y otro:
    - Regional: "Raichu-Alola" -> "Raichu [Alolan Form]"
    - Regional con variante extra: "Tauros-Paldea-Aqua" ->
      "Tauros [Paldean Form (Aqua Breed)]"
    - Rotom: "Rotom-Heat" -> "Heat Rotom" (el CSV lo pone como prefijo,
      no como corchete)
    - Género: "Basculegion-F" -> "Basculegion [Female]"
    Devuelve una lista de candidatos a probar contra el roster (puede
    haber más de uno para la misma variante, por si el CSV redactó el
    corchete un poco distinto).
    """
    parts = raw.split("-")
    if len(parts) < 2:
        return []
    base = parts[0]
    candidates: List[str] = []

    if base.lower() == "rotom" and len(parts) == 2:
        candidates.append(f"{parts[1]} Rotom")

    region_key = parts[1].lower()
    if region_key in _REGION_ADJECTIVE:
        adjective = _REGION_ADJECTIVE[region_key]
        if len(parts) == 2:
            candidates.append(f"{base} [{adjective} Form]")
        elif len(parts) >= 3:
            extra = parts[2]
            candidates.append(f"{base} [{adjective} Form ({extra} Breed)]")
            candidates.append(f"{base} [{adjective} Form ({extra})]")

    if len(parts) == 2 and parts[1].upper() in ("F", "FEMALE"):
        candidates.append(f"{base} [Female]")
    if len(parts) == 2 and parts[1].upper() in ("M", "MALE"):
        candidates.append(f"{base} [Male]")

    return candidates


# Lookup nombre-normalizado -> nombre EXACTO del roster (tal como está en
# el CSV), para los Pokémon seleccionables (bases, no filas de Mega). Se
# guardan también variantes con guion<->espacio, porque Showdown y el CSV
# no siempre coinciden en cuál de los dos usan (ej. "Sinistcha-Masterpiece"
# vs "Sinistcha Masterpiece").
_TEAM_SELECTOR_LOOKUP: Dict[str, str] = {}
for _name in TEAM_SELECTOR_NAMES:
    _key = _normalize_name(_name)
    for _variant in (_key, _key.replace("-", " "), _key.replace(" ", "-")):
        _TEAM_SELECTOR_LOOKUP.setdefault(_variant, _name)

# Mismo lookup pero sobre TODO el roster (incluidas las filas de Mega),
# como último recurso si el nombre importado ya viene directamente en
# forma de Mega y no matcheó nada arriba.
_ALL_NAME_LOOKUP: Dict[str, str] = {}
for _p in POKEMON_DATA:
    _key = _normalize_name(_p["name"])
    for _variant in (_key, _key.replace("-", " "), _key.replace(" ", "-")):
        _ALL_NAME_LOOKUP.setdefault(_variant, _p["name"])


def _match_species(raw: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Resuelve un nombre tal como viene de Showdown contra el roster.
    Devuelve `(nombre_base, nombre_de_mega_o_None)`:
    - Si es un Pokémon normal: `(nombre_base, None)`.
    - Si es una forma Mega (ej. "Chesnaught-Mega", "Raichu-Mega-Y"): el
      nombre BASE (el que va en `my_team`/`rival_team`) más el nombre
      exacto de la fila de Mega correspondiente (para activar
      `mega_active` y elegir la variante correcta en `mega_choice`).
    - Si no matchea nada: `(None, None)`.
    """
    raw = _strip_trailing_gender_marker(raw.strip())
    variant = None
    base_raw = None

    m = re.match(r"^(.*)-Mega-([XYxy])$", raw)
    if m:
        base_raw, variant = m.group(1), m.group(2).upper()
    else:
        m = re.match(r"^(.*)-Mega$", raw, re.IGNORECASE)
        if m:
            base_raw = m.group(1)

    if base_raw is not None:
        base_key = _normalize_name(base_raw)
        base_name = _TEAM_SELECTOR_LOOKUP.get(base_key)
        if base_name and POKEMON_MEGA_COUNT.get(base_name, 0) > 0:
            megas = POKEMON_MEGA_OF_BASE[base_name]
            if variant:
                for mega_name in megas:
                    if mega_name.upper().endswith(variant):
                        return base_name, mega_name
            return base_name, megas[0]
        # No se pudo resolver como Mega (nombre raro) -> probar tal cual
        # sigue abajo con el string original completo.

    direct_key = _normalize_name(raw)
    direct = _TEAM_SELECTOR_LOOKUP.get(direct_key)
    if direct:
        return direct, None

    # Formas regionales / Rotom / género que el CSV escribe distinto que
    # Showdown (corchetes vs. guiones) -- ver `_build_form_candidates`.
    for candidate in _build_form_candidates(raw):
        candidate_key = _normalize_name(candidate)
        direct = _TEAM_SELECTOR_LOOKUP.get(candidate_key)
        if direct:
            return direct, None

    # Fallback genérico: hay formas de Showdown que en el CSV directamente
    # NO tienen fila propia porque no cambian Base Speed (ej.
    # "Sinistcha-Masterpiece" -> el CSV solo tiene "Sinistcha",
    # "Maushold-Four" -> solo "Maushold"). Vamos sacando el último
    # segmento con guion hasta encontrar algo que sí exista en el roster.
    stripped_parts = raw.split("-")
    while len(stripped_parts) > 1:
        stripped_parts = stripped_parts[:-1]
        candidate_key = _normalize_name("-".join(stripped_parts))
        direct = _TEAM_SELECTOR_LOOKUP.get(candidate_key)
        if direct:
            return direct, None

    # Último recurso: el nombre importado coincide EXACTO con una fila de
    # Mega del CSV (poco común, pero por si acaso) -> resolver a su base.
    any_match = _ALL_NAME_LOOKUP.get(direct_key)
    if any_match:
        base_of = POKEMON_MEGA_FROM.get(any_match)
        if base_of:
            return base_of, any_match
        return any_match, None

    # Fallback difuso, por errores de tipeo o pequeñas variaciones de
    # formato que no cubrieron los casos de arriba.
    close = difflib.get_close_matches(
        direct_key, list(_TEAM_SELECTOR_LOOKUP.keys()), n=1, cutoff=0.82
    )
    if close:
        return _TEAM_SELECTOR_LOOKUP[close[0]], None

    return None, None


# Líneas que NO arrancan un nuevo Pokémon dentro de un bloque de import:
# cualquier otra línea no vacía se interpreta como el header
# "Nombre @ Item" (o solo "Nombre") de un Pokémon nuevo.
_SHOWDOWN_FIELD_PATTERNS = [
    re.compile(r"^Ability:", re.IGNORECASE),
    re.compile(r"^Level:", re.IGNORECASE),
    re.compile(r"^Shiny:", re.IGNORECASE),
    re.compile(r"^EVs:", re.IGNORECASE),
    re.compile(r"^IVs:", re.IGNORECASE),
    re.compile(r"^Happiness:", re.IGNORECASE),
    re.compile(r"^Tera Type:", re.IGNORECASE),
    re.compile(r"^Gender:", re.IGNORECASE),
    re.compile(r"^Hidden Power:", re.IGNORECASE),
    re.compile(r"^-"),  # movimientos
    re.compile(r"^\w[\w\s]*\bNature$", re.IGNORECASE),
]


class ImportedMon(TypedDict):
    raw_name: str
    species: Optional[str]
    mega: Optional[str]
    ev_spe: int
    nature: str


def _parse_showdown_team(text: str) -> List[ImportedMon]:
    """
    Parsea texto exportado por Showdown, con o SIN línea en blanco entre
    cada Pokémon (algunos exports vienen sin separador). Por cada bloque
    extrae únicamente lo que le importa a la app: especie (ya resuelta
    contra el roster), EVs de Speed y naturaleza (solo si afecta Speed).
    Todo lo demás (item, habilidad, movimientos, IVs, Tera Type, etc.) se
    descarta. Si un nombre no matchea ningún Pokémon del roster, ese
    bloque se devuelve con `species=None` para que el caller pueda
    avisarle al usuario en vez de fallar en silencio.
    """
    blocks: List[List[str]] = []
    current: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                blocks.append(current)
                current = []
            continue
        is_field = any(p.match(line) for p in _SHOWDOWN_FIELD_PATTERNS)
        if not is_field and current:
            blocks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append(current)

    results: List[ImportedMon] = []
    for block in blocks:
        header = block[0]
        name_part = header.split(" @ ")[0].strip()
        ev_spe = 0
        nature_effect = ""
        for line in block[1:]:
            ev_m = re.match(r"^EVs:\s*(.+)$", line, re.IGNORECASE)
            if ev_m:
                for chunk in ev_m.group(1).split("/"):
                    spe_m = re.match(r"^(\d+)\s+Spe$", chunk.strip(), re.IGNORECASE)
                    if spe_m:
                        ev_spe = int(spe_m.group(1))
            nat_m = re.match(r"^(\w+)\s+Nature$", line, re.IGNORECASE)
            if nat_m:
                nature_effect = NATURE_SPEED_EFFECT.get(nat_m.group(1).lower(), "")
        species, mega = _match_species(name_part)
        results.append({
            "raw_name": name_part,
            "species": species,
            "mega": mega,
            "ev_spe": max(0, min(SPEED_EV_MAX, ev_spe)),
            "nature": nature_effect,
        })
    return results


def _stage_multiplier(stage: int) -> float:
    """
    Tabla estándar de multiplicador por stat stage (el contador -6..+6):
        stage >= 0:  (2 + stage) / 2   (+1 = ×1.5, +2 = ×2, ... +6 = ×4)
        stage <  0:  2 / (2 - stage)   (-1 = ×0.67, -2 = ×0.5, ... -6 = ×0.25)
    """
    stage = max(-6, min(6, stage))
    if stage >= 0:
        return (2 + stage) / 2
    return 2 / (2 - stage)


def _ability_multiplier(ability: str) -> float:
    """
    Multiplicador de Speed cuando el botón de habilidad está activo. Todas
    las habilidades relevantes dan x2 (Swift Swim, Chlorophyll, Sand Rush,
    etc.), excepto Quick Feet, que da x1.5. Si la casilla no tiene ninguna
    habilidad cargada (""), no aplica nada (x1).
    """
    if ability == "Quick Feet":
        return 1.5
    if ability:
        return 2.0
    return 1.0


def _calc_speed(
    base: int, ev: int, nature: str, stage: int, scarf: bool, para: bool,
    ability: str = "", ability_active: bool = False, tailwind: bool = False,
) -> int:
    """
    Fórmula de stat de Speed, con Nivel 50 e IV 31 fijos (formato Pokémon
    Champions). En este formato los EVs van directo de 0 a 32 -- cada punto
    suma 1 al cálculo, SIN dividir entre 4 como en el formato clásico
    (252 EVs / 4).

        stat = floor((2*base + IV + EV) * Nivel / 100) + 5

    Después, en el mismo orden que el motor real:
        1. Se aplica la naturaleza (±10%, o neutra si no se eligió
           ninguna), con floor propio.
        2. Se aplica el stat stage (el contador -6..+6), con floor propio.
        3. Se aplican los modificadores de item/habilidad/estado/campo
           combinados multiplicando antes de un único floor final:
           - Choice Scarf: ×1.5
           - Habilidad (si el botón está activo): x2, o x1.5 si es Quick Feet
           - Tailwind (si está activo para ese equipo): ×2
           - Parálisis (gens modernas): ×0.5

    `nature` es "pos" (+10%), "neg" (-10%) o "" (neutra, sin selección).
    `ability` es el nombre de la habilidad relevante para Speed de ese
    Pokémon ("" si no tiene ninguna); `ability_active` es el toggle del
    botón en la UI, que solo aparece cuando `ability` no está vacío.
    `tailwind` es el toggle de equipo (no por Pokémon), ver
    `PokemonState.my_tailwind` / `rival_tailwind`.
    """
    if base <= 0:
        return 0
    stat = (2 * base + SPEED_IV + ev) * SPEED_LEVEL // 100 + 5
    nature_multiplier = 1.1 if nature == "pos" else 0.9 if nature == "neg" else 1.0
    natured = int(stat * nature_multiplier)
    staged = int(natured * _stage_multiplier(stage))
    multiplier = 1.0
    if scarf:
        multiplier *= 1.5
    if ability_active:
        multiplier *= _ability_multiplier(ability)
    if tailwind:
        multiplier *= 2.0
    if para:
        multiplier *= 0.5
    return int(staged * multiplier)


class PokemonState(rx.State):
    my_team: List[str] = [""] * TEAM_SIZE
    rival_team: List[str] = [""] * TEAM_SIZE

    is_open: bool = False
    current_index: int = 0
    current_side: str = ""  # "my" | "rival"
    matchup_saved: bool = False

    # -----------------------------------------------------------------
    # Equipos propios guardados. Se persisten en el localStorage del
    # navegador (sobreviven a un refresh/cierre de pestaña) como un
    # string JSON, porque `rx.LocalStorage` solo soporta tipos simples
    # -- una lista de dicts anidados no viaja directo. El computed var
    # `saved_teams` de abajo es el que parsea ese JSON para el resto de
    # la lógica.
    #
    # A propósito solo se guardan equipos PROPIOS ("my_team"), nunca el
    # rival: lo que uno arma y reutiliza partida a partida es su propio
    # equipo, el rival cambia cada vez.
    # -----------------------------------------------------------------
    saved_teams_raw: str = rx.LocalStorage("[]", name="pc_saved_teams")

    save_team_open: bool = False
    save_team_name: str = ""
    save_team_error: str = ""
    saved_teams_open: bool = False

    # --- "Save matchup": guarda una fila (mi equipo / equipo rival /
    # resultado) en el Excel de historial (`MATCHUP_LOG_PATH`), no en
    # localStorage -- ver `_append_matchup_result`.
    save_matchup_open: bool = False
    save_matchup_error: str = ""
    last_matchup_result: str = ""  # "Victoria" | "Derrota" | "" (para el ✓)

    match_history_open: bool = False
    match_history: List[str] = []
    match_history_error: str = ""

    # Búsqueda dentro del diálogo de selección
    search_query: str = ""

    # Hasta 4 Pokémon marcados de CADA equipo, para el panel de análisis.
    # Solo tienen efecto una vez que ese equipo está completo (6/6).
    my_selected: List[bool] = [False] * TEAM_SIZE
    rival_selected: List[bool] = [False] * TEAM_SIZE

    # Stats por slot global: 0-5 = my_team, 6-11 = rival_team
    speed_evs: List[int] = [0] * (TEAM_SIZE * 2)
    buffs: List[int] = [0] * (TEAM_SIZE * 2)
    scarf: List[bool] = [False] * (TEAM_SIZE * 2)
    para: List[bool] = [False] * (TEAM_SIZE * 2)
    # Toggle del botón de habilidad. Solo tiene efecto/se muestra para los
    # Pokémon cuyo POKEMON_ABILITY no está vacío.
    ability_active: List[bool] = [False] * (TEAM_SIZE * 2)
    # Toggle del botón de Mega. Solo tiene efecto/se muestra para los
    # Pokémon cuyo POKEMON_MEGA_COUNT es > 0. Al activarse, reemplaza el
    # Base Speed normal por el de la Mega elegida (cambio de forma, no
    # multiplicador).
    mega_active: List[bool] = [False] * (TEAM_SIZE * 2)
    # Índice (dentro de POKEMON_MEGA_OF_BASE[nombre_base]) de CUÁL Mega está
    # elegida para ese slot, para los Pokémon con más de una (ej. Charizard
    # -> Mega Charizard X/Y). Con una sola Mega este índice siempre es 0 y
    # no hace falta elegir nada.
    mega_choice: List[int] = [0] * (TEAM_SIZE * 2)
    # Naturaleza de Speed: "" (neutra, sin elegir), "pos" (+10%), "neg" (-10%)
    nature: List[str] = [""] * (TEAM_SIZE * 2)
    # Colapsa/expande la sección de Speed EVs + Naturaleza en cada tarjeta,
    # para no mostrar tanto dato de una: arranca oculta.
    show_details: List[bool] = [False] * (TEAM_SIZE * 2)

    # --- Diálogo de import (formato Showdown) ---
    import_open: bool = False
    import_side: str = "my"  # "my" | "rival"
    import_text: str = ""
    # Nombres crudos (tal como vinieron del texto pegado) que no se
    # pudieron matchear contra el roster en el último intento de import.
    import_errors: List[str] = []

    # Tema de la PÁGINA (solo el fondo, ver PAGE_BACKGROUND_*). Arranca en
    # oscuro; el botón de la esquina inferior derecha lo alterna.
    light_theme: bool = False

    # Toggle único por equipo (no por Pokémon): Tailwind duplica la Speed
    # de los 4 activos de ese lado mientras está prendido.
    my_tailwind: bool = False
    rival_tailwind: bool = False

    # Toggle único y global (no hay "mi" o "rival" Trick Room, afecta la
    # cancha entera): invierte el orden de movimiento en `turn_order`.
    trick_room: bool = False

    @rx.var(cache=True)
    def pokemon_images(self) -> Dict[str, str]:
        return POKEMON_IMAGES

    @rx.var(cache=True)
    def pokemon_ability(self) -> Dict[str, str]:
        return POKEMON_ABILITY

    @rx.var(cache=True)
    def pokemon_mega_count(self) -> Dict[str, int]:
        return POKEMON_MEGA_COUNT

    @rx.var(cache=True)
    def pokemon_mega_of_base(self) -> Dict[str, List[str]]:
        """Nombre-base -> lista de nombres de sus Megas (1 elemento para la
        mayoría, 2 para los que tienen doble Mega como Charizard/Raichu).
        Se usa en la UI para armar el selector de "cuál Mega" y para saber
        qué sprite/nombre/habilidad mostrar cuando `mega_active` está
        prendido para ese slot (la Mega es una fila propia del roster,
        con su propio sprite y su propia habilidad)."""
        return POKEMON_MEGA_OF_BASE

    def _effective_name(self, name: str, global_index: int) -> str:
        """Nombre "efectivo" de un slot: si Mega está activa y ese
        Pokémon tiene Mega(s) cargada(s), la Mega elegida en
        `mega_choice` (mod la cantidad disponible, para no romper si el
        slot cambió de Pokémon y quedó un índice viejo); si no, el nombre
        base tal cual está en el equipo."""
        megas = POKEMON_MEGA_OF_BASE.get(name, [])
        if self.mega_active[global_index] and megas:
            choice = self.mega_choice[global_index] % len(megas)
            return megas[choice]
        return name

    @rx.var(cache=True)
    def effective_names(self) -> List[str]:
        """Nombre efectivo por slot global (0-5 = my_team, 6-11 =
        rival_team). Usado tanto acá para `computed_speeds` como en la UI
        (sprite, nombre, habilidad) para no duplicar la lógica de elegir
        la Mega correcta."""
        names: List[str] = [self._effective_name(self.my_team[i], i) for i in range(TEAM_SIZE)]
        names += [
            self._effective_name(self.rival_team[i], TEAM_SIZE + i) for i in range(TEAM_SIZE)
        ]
        return names

    @rx.var(cache=True)
    def computed_speeds(self) -> List[int]:
        """
        Velocidad real por slot global (0-5 = my_team, 6-11 = rival_team),
        recalculada en vivo con los EVs, la naturaleza (±10%/neutra), el
        stat stage (buffs -6..+6) y los toggles de Scarf/Ability/PAR
        actuales. Si el toggle de Mega está activo, se usa el Base Speed
        de la Mega elegida (`mega_choice`) en vez del normal -- es un
        cambio de forma, no un multiplicador más. Cada Mega es su propia
        fila del roster, así que su Base Speed sale directo de
        POKEMON_BASE_SPEED igual que cualquier otro Pokémon. 0 si esa
        casilla está vacía o el Pokémon no tiene base speed cargada.
        """
        speeds: List[int] = []
        for i in range(TEAM_SIZE):
            effective_name = self.effective_names[i]
            base = POKEMON_BASE_SPEED.get(effective_name, 0)
            ability = POKEMON_ABILITY.get(effective_name, "")
            speeds.append(
                _calc_speed(
                    base, self.speed_evs[i], self.nature[i], self.buffs[i],
                    self.scarf[i], self.para[i], ability, self.ability_active[i],
                    self.my_tailwind,
                )
            )
        for i in range(TEAM_SIZE):
            gi = TEAM_SIZE + i
            effective_name = self.effective_names[gi]
            base = POKEMON_BASE_SPEED.get(effective_name, 0)
            ability = POKEMON_ABILITY.get(effective_name, "")
            speeds.append(
                _calc_speed(
                    base, self.speed_evs[gi], self.nature[gi], self.buffs[gi],
                    self.scarf[gi], self.para[gi], ability, self.ability_active[gi],
                    self.rival_tailwind,
                )
            )
        return speeds

    @rx.var(cache=True)
    def filtered_pokemon_options(self) -> List[str]:
        """
        Lista filtrada por `search_query` (case-insensitive, substring),
        sobre `TEAM_SELECTOR_NAMES` -- es decir, solo los Pokémon marcados
        "Yes" en MegaEvolve. Las filas "No" y las de Mega en sí no
        aparecen acá, aunque sigan existiendo para el resto de la lógica
        (Base Speed, sprite, el botón de Mega una vez elegido el base).
        """
        if not self.search_query:
            return TEAM_SELECTOR_NAMES
        q = self.search_query.lower()
        return [name for name in TEAM_SELECTOR_NAMES if q in name.lower()]

    @rx.var(cache=True)
    def has_import_errors(self) -> bool:
        return len(self.import_errors) > 0

    @rx.var(cache=True)
    def import_errors_text(self) -> str:
        return ", ".join(self.import_errors)

    @rx.var(cache=True)
    def my_complete(self) -> bool:
        return all(name != "" for name in self.my_team)

    @rx.var(cache=True)
    def rival_complete(self) -> bool:
        return all(name != "" for name in self.rival_team)

    @rx.var(cache=True)
    def my_selection_full(self) -> bool:
        """True solo cuando ya hay 4 Pokémon míos marcados para el panel
        de stats (el máximo). Se usa para grisar los 2 que quedaron
        afuera -- si se destilda uno, esto pasa a False y todos vuelven
        a verse normales."""
        return sum(self.my_selected) >= 4

    @rx.var(cache=True)
    def rival_selection_full(self) -> bool:
        """Igual que `my_selection_full` pero para el equipo rival."""
        return sum(self.rival_selected) >= 4

    @rx.var(cache=True)
    def my_active_slots(self) -> List[SlotInfo]:
        """Hasta 4 Pokémon de mi equipo marcados para el panel de stats.
        Vacío hasta que mi equipo esté completo."""
        if not self.my_complete:
            return []
        return [
            {"global_index": i, "side": "my", "name": self.my_team[i]}
            for i in range(TEAM_SIZE)
            if self.my_selected[i]
        ]

    @rx.var(cache=True)
    def rival_active_slots(self) -> List[SlotInfo]:
        """Hasta 4 Pokémon del rival marcados para el panel de stats.
        Vacío hasta que el equipo rival esté completo."""
        if not self.rival_complete:
            return []
        return [
            {"global_index": TEAM_SIZE + i, "side": "rival", "name": self.rival_team[i]}
            for i in range(TEAM_SIZE)
            if self.rival_selected[i]
        ]

    @rx.var(cache=True)
    def has_my_active(self) -> bool:
        return len(self.my_active_slots) > 0

    @rx.var(cache=True)
    def has_rival_active(self) -> bool:
        return len(self.rival_active_slots) > 0

    @rx.var(cache=True)
    def has_active_slots(self) -> bool:
        return self.has_my_active or self.has_rival_active

    @rx.var(cache=True)
    def turn_order(self) -> List[int]:
        """Orden de movimiento (1 = se mueve primero) entre TODOS los
        slots activos actualmente mostrados (mío + rival mezclados,
        como en un turno real). Se ordena por `computed_speeds`
        descendente -- o ASCENDENTE si `trick_room` está activo, ya que
        Trick Room invierte el orden de movimiento (el más lento se
        mueve primero). Los que EMPATAN en velocidad comparten el mismo
        número (ej. dos con la misma velocidad más alta son ambos "1",
        y el siguiente pasa a ser "3", no "2" -- ranking tipo
        competencia, salteando los puestos ocupados por el empate).
        Lista de tamaño fijo indexada por global_index; 0 para los
        slots que no están activos (no se muestran en el panel, así
        que no se les asigna número)."""
        order = [0] * (TEAM_SIZE * 2)
        active_indices = [s["global_index"] for s in self.my_active_slots]
        active_indices += [s["global_index"] for s in self.rival_active_slots]
        for gi in active_indices:
            speed = self.computed_speeds[gi]
            if self.trick_room:
                rank = 1 + sum(
                    1 for other in active_indices if self.computed_speeds[other] < speed
                )
            else:
                rank = 1 + sum(
                    1 for other in active_indices if self.computed_speeds[other] > speed
                )
            order[gi] = rank
        return order

    @rx.var(cache=True)
    def show_divider(self) -> bool:
        """La línea divisoria entre 'tu equipo' y 'rival' en el panel de
        stats solo aparece si hay elementos marcados de AMBOS lados."""
        return self.has_my_active and self.has_rival_active

    @rx.var(cache=True)
    def saved_teams(self) -> List[Dict]:
        """
        Lista de equipos propios guardados, parseada desde
        `saved_teams_raw`. Cada entrada: `{"name": str, "slots": [...6
        TeamSlotSnapshot...], "tailwind": bool}`. Si el JSON está
        corrupto, ausente, o todavía no se guardó nada, devuelve lista
        vacía en vez de romper el render (`saved_teams_raw` arranca en
        `"[]"`, pero un valor viejo/manual en localStorage podría no
        ser JSON válido).
        """
        try:
            data = json.loads(self.saved_teams_raw)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    @rx.var(cache=True)
    def saved_team_names(self) -> List[str]:
        """Solo los nombres, para listar en la UI sin tener que tipar
        todo el Dict anidado como Var (ver `saved_team_row`)."""
        return [t.get("name", "") for t in self.saved_teams]

    @rx.var(cache=True)
    def has_saved_teams(self) -> bool:
        return len(self.saved_teams) > 0

    def open_selector(self, index: int, side: str):
        self.current_index = index
        self.current_side = side
        self.search_query = ""
        self.is_open = True

    def select_pokemon(self, name: str):
        if self.current_side == "my":
            self.my_team[self.current_index] = name
        else:
            self.rival_team[self.current_index] = name
        self.is_open = False
        self.search_query = ""

    def close_selector(self):
        self.is_open = False
        self.search_query = ""

    def set_search_query(self, value: str):
        self.search_query = value

    def remove_pokemon(self, index: int, side: str):
        """Vacía una casilla (mía o del rival). También limpia su marca de
        análisis, ya que ese equipo deja de estar completo."""
        if side == "my":
            self.my_team[index] = ""
            self.my_selected[index] = False
        else:
            self.rival_team[index] = ""
            self.rival_selected[index] = False

    def toggle_my_selection(self, index: int):
        """Marca/desmarca un Pokémon propio para el panel de stats.
        Solo tiene efecto si mi equipo ya está completo, máximo 4 marcados."""
        if not self.my_complete:
            return
        if self.my_selected[index]:
            self.my_selected[index] = False
        elif sum(self.my_selected) < 4:
            self.my_selected[index] = True

    def toggle_rival_selection(self, index: int):
        """Marca/desmarca un Pokémon rival para el panel de stats.
        Solo tiene efecto si el equipo rival ya está completo, máximo 4."""
        if not self.rival_complete:
            return
        if self.rival_selected[index]:
            self.rival_selected[index] = False
        elif sum(self.rival_selected) < 4:
            self.rival_selected[index] = True

    def handle_slot_click(self, index: int, side: str):
        """
        Un único handler para el click principal de cada casilla:
        - Ese equipo YA completo -> el click marca/desmarca ese Pokémon
          para el panel de stats (en vez de reabrir el selector).
        - Cualquier otro caso -> abre el selector para asignar/cambiar
          el Pokémon de esa casilla.
        """
        if side == "my" and self.my_complete:
            self.toggle_my_selection(index)
        elif side == "rival" and self.rival_complete:
            self.toggle_rival_selection(index)
        else:
            self.open_selector(index, side)

    def _slot_snapshot(self, team: List[str], offset: int) -> List[TeamSlotSnapshot]:
        """
        Arma la snapshot de los 6 slots de UN lado (offset=0 para el
        propio, offset=TEAM_SIZE para el rival): especie + toda su
        config de Speed actual. Es de solo lectura (no toca el
        estado). Hoy la usa únicamente `save_my_team` (offset=0) --
        "Save matchup" ya no guarda esta config detallada, solo las
        especies (ver `save_matchup_result`) -- pero se deja general
        por si hace falta reusarla más adelante.
        """
        return [
            {
                "species": team[i],
                "speed_ev": self.speed_evs[offset + i],
                "nature": self.nature[offset + i],
                "scarf": self.scarf[offset + i],
                "para": self.para[offset + i],
                "ability_active": self.ability_active[offset + i],
                "mega_active": self.mega_active[offset + i],
                "mega_choice": self.mega_choice[offset + i],
            }
            for i in range(TEAM_SIZE)
        ]

    def _apply_slots_to_my_team(self, slots: List[Dict]):
        """Vuelca una lista de TeamSlotSnapshot guardada sobre las 6
        casillas propias, reemplazando lo que hubiera (misma lógica de
        'limpiar antes de cargar' que `apply_import`). Si la snapshot
        guardada tiene menos de 6 slots (dato viejo/corrupto), las que
        faltan quedan vacías en vez de romper."""
        for i in range(TEAM_SIZE):
            slot = slots[i] if i < len(slots) else _empty_slot_snapshot()
            self.my_team[i] = slot.get("species", "")
            self.speed_evs[i] = slot.get("speed_ev", 0)
            self.nature[i] = slot.get("nature", "")
            self.scarf[i] = slot.get("scarf", False)
            self.para[i] = slot.get("para", False)
            self.ability_active[i] = slot.get("ability_active", False)
            self.mega_active[i] = slot.get("mega_active", False)
            self.mega_choice[i] = slot.get("mega_choice", 0)
            self.my_selected[i] = False

    # --- Guardar / cargar / borrar EQUIPOS propios ---------------------

    def open_save_team(self):
        self.save_team_name = ""
        self.save_team_error = ""
        self.save_team_open = True

    def close_save_team(self):
        self.save_team_open = False

    def set_save_team_name(self, value: str):
        self.save_team_name = value

    def save_my_team(self):
        """
        Guarda el equipo propio actual (6 casillas + toda su config de
        Speed) bajo el nombre tipeado en el diálogo, persistiendo en
        localStorage. Si ya existe un equipo guardado con ese mismo
        nombre, lo pisa (permite "actualizar" sin acumular duplicados).
        Exige nombre no vacío y equipo completo (6/6) -- si falta algo,
        se muestra el error en el diálogo en vez de guardar algo a
        medias que después no sirva para nada.
        """
        name = self.save_team_name.strip()
        if not name:
            self.save_team_error = "Ponele un nombre al equipo."
            return
        if not self.my_complete:
            self.save_team_error = "Completá las 6 casillas antes de guardar."
            return
        entry = {
            "name": name,
            "slots": self._slot_snapshot(self.my_team, 0),
            "tailwind": self.my_tailwind,
        }
        teams = [t for t in self.saved_teams if t.get("name") != name]
        teams.append(entry)
        self.saved_teams_raw = json.dumps(teams)
        self.save_team_open = False

    def load_saved_team(self, name: str):
        """Carga un equipo guardado en las casillas propias (0-5),
        reemplazando lo que hubiera ahí."""
        entry = next((t for t in self.saved_teams if t.get("name") == name), None)
        if entry is None:
            return
        self._apply_slots_to_my_team(entry.get("slots", []))
        self.my_tailwind = entry.get("tailwind", False)
        self.saved_teams_open = False

    def delete_saved_team(self, name: str):
        teams = [t for t in self.saved_teams if t.get("name") != name]
        self.saved_teams_raw = json.dumps(teams)

    def open_saved_teams(self):
        self.saved_teams_open = True

    def close_saved_teams(self):
        self.saved_teams_open = False

    # --- "Save matchup": registrar el resultado de la partida ----------
    #
    # A diferencia de "Guardar equipo" (que persiste en localStorage
    # para reusar en el navegador), esto va a un Excel en disco
    # (`MATCHUP_LOG_PATH`) porque la idea es un registro histórico --
    # mi equipo, el equipo rival, y si gané o perdí -- pensado para
    # analizarse más adelante (ej. abrir el Excel y ver win rate contra
    # ciertos Pokémon). No guarda EVs/naturaleza/etc., solo las 6
    # especies de cada lado: para eso ya está "Guardar equipo".

    def open_save_matchup(self):
        self.save_matchup_error = ""
        self.matchup_saved = False
        self.save_matchup_open = True

    def close_save_matchup(self):
        self.save_matchup_open = False

    def save_matchup_result(self, result: str):
        """
        Agrega una fila al Excel de historial con los 6 Pokémon
        propios, los 6 rivales, y `result` ("Victoria" o "Derrota" --
        lo que sea que hayan mandado los botones del diálogo). Exige
        los dos equipos completos (6/6); si falta algo, muestra el
        error en el diálogo en vez de guardar una fila incompleta.
        """
        if not (self.my_complete and self.rival_complete):
            self.save_matchup_error = "Completá los dos equipos (6/6) antes de guardar."
            return
        error = _append_matchup_result(list(self.my_team), list(self.rival_team), result)
        if error:
            self.save_matchup_error = error
            return
        self.matchup_saved = True
        self.last_matchup_result = result
        self.save_matchup_open = False

    def open_match_history(self):
        """Lee `MATCHUP_LOG_PATH` de nuevo cada vez que se abre el
        diálogo (no se cachea en `saved_teams`-style porque el Excel
        puede haber cambiado por fuera de la app)."""
        rows, error = _read_matchup_history()
        self.match_history = rows
        self.match_history_error = error or ""
        self.match_history_open = True

    def close_match_history(self):
        self.match_history_open = False

    def set_speed_ev_input(self, global_index: int, value: str):
        """

        Handler del input numérico de Speed EVs (reemplaza al slider).
        Formato Pokémon Champions: EVs van de 0 a 32, cada punto entero es
        exacto (ej. 1, 20, 32) -- no hay conversión ni redondeo a
        múltiplos de 4 como en el formato clásico. Si el input queda vacío
        o no es un número válido mientras el usuario está tipeando, no
        rompe: lo trata como 0 en vez de tirar una excepción.
        """
        try:
            v = int(value)
        except (ValueError, TypeError):
            v = 0
        self.speed_evs[global_index] = max(0, min(SPEED_EV_MAX, v))

    def set_speed_ev_max(self, global_index: int):
        """Atajo: máxima inversión posible de Speed EVs (32 en este formato)."""
        self.speed_evs[global_index] = SPEED_EV_MAX

    def set_speed_ev_min(self, global_index: int):
        """Atajo: cero inversión de Speed EVs."""
        self.speed_evs[global_index] = 0

    def set_buff(self, global_index: int, value: List[int]):
        self.buffs[global_index] = value[0]

    def increment_buff(self, global_index: int):
        """Sube el buff en 1, tope +6."""
        if self.buffs[global_index] < 6:
            self.buffs[global_index] += 1

    def decrement_buff(self, global_index: int):
        """Baja el buff en 1, piso -6."""
        if self.buffs[global_index] > -6:
            self.buffs[global_index] -= 1

    def toggle_scarf(self, global_index: int):
        self.scarf[global_index] = not self.scarf[global_index]

    def toggle_para(self, global_index: int):
        self.para[global_index] = not self.para[global_index]

    def toggle_ability(self, global_index: int):
        """Solo tiene efecto real en el cálculo si ese slot tiene una
        habilidad cargada (ver `_calc_speed`); el botón en la UI ya se
        oculta para los Pokémon sin habilidad relevante."""
        self.ability_active[global_index] = not self.ability_active[global_index]

    def toggle_mega(self, global_index: int):
        """Solo tiene efecto real en el cálculo si ese slot tiene alguna
        Mega cargada (ver `computed_speeds`); el botón en la UI ya se
        oculta para los Pokémon que no megaevolucionan. Al prenderse usa
        por defecto la Mega en `mega_choice` (la primera del CSV si nunca
        se tocó el selector); para elegir otra ver `select_mega`."""
        self.mega_active[global_index] = not self.mega_active[global_index]

    def toggle_my_tailwind(self):
        """Tailwind (Viento Afín) duplica la Speed de TODO mi equipo en
        pantalla -- a diferencia de Scarf/PAR/Mega, no es un toggle por
        Pokémon sino un único switch que afecta a los 4 activos míos."""
        self.my_tailwind = not self.my_tailwind

    def toggle_rival_tailwind(self):
        """Igual que `toggle_my_tailwind` pero para el equipo rival."""
        self.rival_tailwind = not self.rival_tailwind

    def toggle_trick_room(self):
        """Trick Room invierte el orden de movimiento: con esto activo,
        el Pokémon MÁS LENTO se mueve primero. No cambia ninguna Speed,
        solo invierte cómo se ordena `turn_order`."""
        self.trick_room = not self.trick_room

    def select_mega(self, global_index: int, mega_name: str):
        """Elige CUÁL Mega usar en un slot con más de una disponible (ej.
        Charizard -> Mega Charizard X/Y). Guarda el índice de `mega_name`
        dentro de la lista de Megas del Pokémon base de ese slot y activa
        la Mega si todavía no estaba activa."""
        name = self.my_team[global_index] if global_index < TEAM_SIZE else self.rival_team[global_index - TEAM_SIZE]
        megas = POKEMON_MEGA_OF_BASE.get(name, [])
        if mega_name in megas:
            self.mega_choice[global_index] = megas.index(mega_name)
        self.mega_active[global_index] = True

    def toggle_nature_negative(self, global_index: int):
        """
        Botón 'Naturaleza -' (-10%):
        - Si ya estaba marcado 'neg' -> lo saca, vuelve a neutra ("").
        - Si estaba en cualquier otro estado (neutra o 'pos') -> pasa a
          'neg' directamente, desmarcando 'pos' si estaba marcado (son
          mutuamente excluyentes, cada slot solo guarda un string).
        """
        if self.nature[global_index] == "neg":
            self.nature[global_index] = ""
        else:
            self.nature[global_index] = "neg"

    def toggle_nature_positive(self, global_index: int):
        """Botón 'Naturaleza +' (+10%), misma lógica que el de negativa."""
        if self.nature[global_index] == "pos":
            self.nature[global_index] = ""
        else:
            self.nature[global_index] = "pos"

    def toggle_details(self, global_index: int):
        """Colapsa/expande la sección de Speed EVs + Naturaleza de la
        tarjeta, para no saturar de datos la vista por defecto."""
        self.show_details[global_index] = not self.show_details[global_index]

    def open_import(self, side: str):
        self.import_side = side
        self.import_text = ""
        self.import_errors = []
        self.import_open = True

    def close_import(self):
        self.import_open = False

    def toggle_theme(self):
        self.light_theme = not self.light_theme

    def set_import_text(self, value: str):
        self.import_text = value

    def apply_import(self):
        """
        Parsea `import_text` con `_parse_showdown_team` y REEMPLAZA por
        completo el equipo elegido (`import_side`) -- limpia las 6
        casillas de ese lado (Pokémon, EVs, naturaleza, Mega, Scarf, PAR,
        habilidad, buffs, selección) antes de cargar lo nuevo, para que
        no queden datos viejos pisados con los de un import parcial.

        Los bloques que no matchearon ningún Pokémon del roster se
        omiten y quedan listados en `import_errors` para mostrarle al
        usuario cuáles no se pudieron importar; si hubo al menos un
        error el diálogo se queda abierto (para que pueda ver el aviso),
        si no, se cierra solo.
        """
        parsed = _parse_showdown_team(self.import_text)
        side = self.import_side
        offset = 0 if side == "my" else TEAM_SIZE
        if side == "my":
            self.my_tailwind = False
        else:
            self.rival_tailwind = False

        for i in range(TEAM_SIZE):
            gi = offset + i
            if side == "my":
                self.my_team[i] = ""
                self.my_selected[i] = False
            else:
                self.rival_team[i] = ""
                self.rival_selected[i] = False
            self.speed_evs[gi] = 0
            self.buffs[gi] = 0
            self.scarf[gi] = False
            self.para[gi] = False
            self.ability_active[gi] = False
            self.mega_active[gi] = False
            self.mega_choice[gi] = 0
            self.nature[gi] = ""
            self.show_details[gi] = False

        errors: List[str] = []
        idx = 0
        for mon in parsed:
            if idx >= TEAM_SIZE:
                break
            if mon["species"] is None:
                errors.append(mon["raw_name"])
                continue
            gi = offset + idx
            if side == "my":
                self.my_team[idx] = mon["species"]
            else:
                self.rival_team[idx] = mon["species"]
            self.speed_evs[gi] = mon["ev_spe"]
            self.nature[gi] = mon["nature"]
            if mon["mega"]:
                megas = POKEMON_MEGA_OF_BASE.get(mon["species"], [])
                if mon["mega"] in megas:
                    self.mega_choice[gi] = megas.index(mon["mega"])
                self.mega_active[gi] = True
            idx += 1

        self.import_errors = errors
        if not errors:
            self.import_open = False


# ---------------------------------------------------------------------------
# Componentes modulares
# ---------------------------------------------------------------------------
def team_slot(team: rx.Var, side: str, index: int) -> rx.Component:
    """
    Una casilla de equipo. `index` y `side` son literales de Python (no
    Vars) porque este componente se construye una vez por cada posición
    fija 0..5 dentro de `team_grid` — por eso los handlers se llaman
    directamente, sin lambdas (ver nota en team_grid).
    """
    is_filled = team[index] != ""

    content = rx.cond(
        is_filled,
        rx.vstack(
            rx.image(
                src=PokemonState.pokemon_images[team[index]],
                width="40px",
                height="40px",
            ),
            rx.text(
                team[index],
                size="1",
                text_align="center",
                style={
                    "white-space": "nowrap",
                    "overflow": "hidden",
                    "text-overflow": "ellipsis",
                    "max-width": "90px",
                },
            ),
            spacing="1",
            align="center",
        ),
        rx.text("+", size="5"),
    )

    # Resalte visual: marca en verde los Pokémon elegidos para el panel de
    # stats. Los que NO están elegidos se ven en gris/apagados únicamente
    # cuando ya se llegó al máximo de 4 seleccionados -- así queda claro
    # que esos 2 quedaron afuera. Si se destilda uno (deja de haber 4),
    # todos los no seleccionados vuelven a verse normales, porque de nuevo
    # cualquiera podría entrar.
    selected_var = PokemonState.rival_selected[index] if side == "rival" else PokemonState.my_selected[index]
    selection_full = PokemonState.rival_selection_full if side == "rival" else PokemonState.my_selection_full
    slot_style = rx.cond(
        selected_var,
        {**PANEL_STYLE, "border": "2px solid #22c55e", "padding": "0"},
        rx.cond(
            selection_full,
            {
                **PANEL_STYLE,
                "border": "1px solid rgba(148, 163, 184, 0.35)",
                "padding": "0",
                "opacity": "0.5",
                "filter": "grayscale(85%)",
            },
            {**PANEL_STYLE, "padding": "0"},
        ),
    )

    main_button = rx.button(
        content,
        on_click=PokemonState.handle_slot_click(index, side),
        width="100%",
        height="80px",
        style=slot_style,
    )

    remove_button = rx.cond(
        is_filled,
        rx.button(
            "×",
            on_click=PokemonState.remove_pokemon(index, side),
            size="1",
            color_scheme="red",
            variant="solid",
            radius="full",
            style={
                "position": "absolute",
                "top": "-6px",
                "right": "-6px",
                "width": "20px",
                "height": "20px",
                "padding": "0",
                "min-width": "0",
            },
        ),
        rx.fragment(),
    )

    return rx.box(main_button, remove_button, position="relative")


def team_grid(team: rx.Var, side: str) -> rx.Component:
    """
    Grid de 6 casillas para un equipo.

    Nota sobre por qué no hacen falta lambdas acá: `range(TEAM_SIZE)` es
    un loop fijo de Python (0..5), que corre una sola vez al construir el
    componente. `i` y `side` ya son literales concretos en ese momento,
    así que se llama al handler directamente
    (`PokemonState.handle_slot_click(i, side)` / `remove_pokemon(i, side)`),
    sin envolver en lambda. Esto evita tanto el bug de closures de Python
    como el bug de inyección de eventos de Reflex (ver historial arriba).
    """
    return rx.grid(
        *[team_slot(team, side, i) for i in range(TEAM_SIZE)],
        columns="3",
        spacing="3",
        width="100%",
    )


def stats_card(slot: rx.Var) -> rx.Component:
    """Tarjeta de stats para un slot activo (Var proveniente de rx.foreach,
    por lo que no sufre el problema de closures: cada iteración de
    rx.foreach genera su propio binding en el JS compilado)."""
    idx = slot["global_index"]

    # Nombre "efectivo" del slot: si Mega está activa, usamos el nombre
    # de la fila de la Mega (que tiene su propio sprite en
    # `pokemon_images` y su propia habilidad en `pokemon_ability`) en vez
    # del nombre del Pokémon base guardado en `slot["name"]`.
    effective_name = PokemonState.effective_names[idx]

    # Stepper numérico de Buffs: "<", número, ">". `idx` viene de un Var
    # reactivo (slot["global_index"] dentro de un rx.foreach), no de un
    # literal fijo de Python, así que puede llamarse directo sin lambda
    # (ver gotcha #2 documentado arriba).
    buff_stepper = rx.hstack(
        rx.button(
            "<",
            on_click=PokemonState.decrement_buff(idx),
            size="1",
            variant="soft",
            color_scheme="gray",
            style={"width": "22px", "height": "22px", "padding": "0", "min-width": "0"},
        ),
        rx.text(
            PokemonState.buffs[idx],
            size="2",
            font_weight="bold",
            width="1.5em",
            text_align="center",
        ),
        rx.button(
            ">",
            on_click=PokemonState.increment_buff(idx),
            size="1",
            variant="soft",
            color_scheme="gray",
            style={"width": "22px", "height": "22px", "padding": "0", "min-width": "0"},
        ),
        spacing="1",
        align="center",
        style={"position": "absolute", "top": "8px", "right": "8px"},
    )

    # Mismo criterio de color que los paneles de la izquierda: azul para
    # "my", rosa para "rival". `slot["side"]` es un Var reactivo, así que
    # se resuelve con rx.cond en vez de un if de Python.
    card_style = rx.cond(slot["side"] == "my", MY_CARD_STYLE, RIVAL_CARD_STYLE)

    # Número de orden de movimiento (1 = se mueve primero), en la esquina
    # opuesta al stepper de buffs para no pisarse con él.
    turn_badge = rx.box(
        rx.text(
            PokemonState.turn_order[idx],
            size="2",
            font_weight="bold",
            color="white",
        ),
        style={
            "position": "absolute",
            "top": "8px",
            "left": "8px",
            "background": "rgba(0, 0, 0, 0.65)",
            "border": "1px solid rgba(255, 255, 255, 0.25)",
            "border-radius": "999px",
            "width": "26px",
            "height": "26px",
            "display": "flex",
            "align-items": "center",
            "justify-content": "center",
            "font-family": "'Montserrat', sans-serif",
        },
    )

    return rx.box(
        buff_stepper,
        turn_badge,
        rx.hstack(
            rx.image(
                src=PokemonState.pokemon_images[effective_name],
                width="110px",
                height="110px",
            ),
            rx.vstack(
                rx.hstack(
                    rx.badge(slot["side"]),
                    rx.text(
                        effective_name,
                        font_weight="bold",
                        size="4",
                        font_family="'Montserrat', sans-serif",
                    ),
                ),
                rx.text(
                    f"Velocidad: {PokemonState.computed_speeds[idx]}",
                    color="#22c55e",
                    font_weight="bold",
                    size="2",
                ),
                rx.button(
                    rx.hstack(
                        rx.text("Speed EVs / Naturaleza", size="2", color_scheme="gray"),
                        rx.cond(
                            PokemonState.show_details[idx],
                            rx.icon(tag="chevron-up", size=14),
                            rx.icon(tag="chevron-down", size=14),
                        ),
                        spacing="1",
                        align="center",
                    ),
                    on_click=PokemonState.toggle_details(idx),
                    variant="ghost",
                    color_scheme="gray",
                    size="1",
                    style={"padding": "0"},
                ),
                rx.cond(
                    PokemonState.show_details[idx],
                    rx.vstack(
                        rx.hstack(
                            rx.input(
                                value=f"{PokemonState.speed_evs[idx]}",
                                on_change=lambda v: PokemonState.set_speed_ev_input(idx, v),
                                type="number",
                                min=0,
                                max=SPEED_EV_MAX,
                                size="1",
                                width="4.5em",
                            ),
                            rx.button(
                                "Min",
                                on_click=PokemonState.set_speed_ev_min(idx),
                                size="1",
                                variant="soft",
                                color_scheme="gray",
                            ),
                            rx.button(
                                "Max",
                                on_click=PokemonState.set_speed_ev_max(idx),
                                size="1",
                                variant="soft",
                                color_scheme="green",
                            ),
                            spacing="1",
                            align="center",
                        ),
                        rx.hstack(
                            rx.button(
                                rx.icon(tag="trending-down", size=16),
                                rx.text("Naturaleza -"),
                                on_click=PokemonState.toggle_nature_negative(idx),
                                variant=rx.cond(PokemonState.nature[idx] == "neg", "solid", "outline"),
                                color_scheme=rx.cond(PokemonState.nature[idx] == "neg", "red", "gray"),
                                size="2",
                            ),
                            rx.button(
                                rx.icon(tag="trending-up", size=16),
                                rx.text("Naturaleza +"),
                                on_click=PokemonState.toggle_nature_positive(idx),
                                variant=rx.cond(PokemonState.nature[idx] == "pos", "solid", "outline"),
                                color_scheme=rx.cond(PokemonState.nature[idx] == "pos", "green", "gray"),
                                size="2",
                            ),
                            spacing="2",
                        ),
                        spacing="2",
                        width="100%",
                        align="start",
                    ),
                ),
                rx.hstack(
                    rx.button(
                        rx.image(src=ICON_SCARF, width="22px", height="22px"),
                        rx.text("Scarf"),
                        on_click=PokemonState.toggle_scarf(idx),
                        variant=rx.cond(PokemonState.scarf[idx], "solid", "outline"),
                        color_scheme=rx.cond(PokemonState.scarf[idx], "blue", "gray"),
                        size="2",
                    ),
                    rx.button(
                        rx.image(src=ICON_PAR, width="22px", height="22px"),
                        rx.text("PAR"),
                        on_click=PokemonState.toggle_para(idx),
                        variant=rx.cond(PokemonState.para[idx], "solid", "outline"),
                        color_scheme=rx.cond(PokemonState.para[idx], "orange", "gray"),
                        size="2",
                    ),
                    rx.cond(
                        PokemonState.pokemon_ability[effective_name] != "",
                        rx.button(
                            rx.image(src=ICON_ABILITY, width="22px", height="22px"),
                            rx.text(PokemonState.pokemon_ability[effective_name]),
                            on_click=PokemonState.toggle_ability(idx),
                            variant=rx.cond(PokemonState.ability_active[idx], "solid", "outline"),
                            color_scheme=rx.cond(PokemonState.ability_active[idx], "purple", "gray"),
                            size="2",
                        ),
                    ),
                    rx.cond(
                        PokemonState.pokemon_mega_count[slot["name"]] > 0,
                        rx.vstack(
                            rx.button(
                                rx.image(src=ICON_MEGA, width="22px", height="22px"),
                                rx.text("Mega"),
                                on_click=PokemonState.toggle_mega(idx),
                                variant=rx.cond(PokemonState.mega_active[idx], "solid", "outline"),
                                color_scheme=rx.cond(PokemonState.mega_active[idx], "cyan", "gray"),
                                size="2",
                            ),
                            # Selector de CUÁL Mega usar, solo quando ese
                            # Pokémon tiene más de una (Charizard, Raichu,
                            # etc.) y la Mega ya está activa.
                            rx.cond(
                                PokemonState.mega_active[idx] & (PokemonState.pokemon_mega_count[slot["name"]] > 1),
                                rx.hstack(
                                    rx.foreach(
                                        PokemonState.pokemon_mega_of_base[slot["name"]],
                                        lambda mega_name: rx.button(
                                            mega_name,
                                            on_click=PokemonState.select_mega(idx, mega_name),
                                            variant=rx.cond(
                                                PokemonState.effective_names[idx] == mega_name,
                                                "solid",
                                                "outline",
                                            ),
                                            color_scheme=rx.cond(
                                                PokemonState.effective_names[idx] == mega_name,
                                                "cyan",
                                                "gray",
                                            ),
                                            size="1",
                                        ),
                                    ),
                                    spacing="1",
                                    style={"flex-wrap": "wrap"},
                                ),
                            ),
                            spacing="1",
                            align="start",
                        ),
                    ),
                    spacing="2",
                    style={"flex-wrap": "wrap"},
                ),
                align="start",
                spacing="2",
                width="100%",
            ),
            align="start",
            spacing="4",
        ),
        style=card_style,
        position="relative",
    )


def selector_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Selecciona un Pokémon"),
            rx.input(
                placeholder="Buscar por nombre...",
                value=PokemonState.search_query,
                on_change=PokemonState.set_search_query,
                margin_bottom="0.75em",
                width="100%",
            ),
            rx.scroll_area(
                rx.vstack(
                    rx.foreach(
                        PokemonState.filtered_pokemon_options,
                        lambda p: rx.button(
                            rx.hstack(
                                rx.image(
                                    src=PokemonState.pokemon_images[p],
                                    width="32px",
                                    height="32px",
                                ),
                                rx.text(p),
                            ),
                            on_click=lambda: PokemonState.select_pokemon(p),
                            width="100%",
                        ),
                    )
                ),
                height="300px",
            ),
            rx.dialog.close(rx.button("Cerrar", on_click=PokemonState.close_selector)),
        ),
        open=PokemonState.is_open,
    )


def import_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Importar equipo (formato Showdown)"),
            rx.text(
                "Pegá el equipo tal cual lo exporta Showdown. Solo se usan "
                "el Pokémon, sus EVs de Speed y su naturaleza (si afecta "
                "Speed) -- lo demás (item, movimientos, IVs, etc.) se "
                "ignora. Esto reemplaza el equipo completo de este lado.",
                size="1",
                color_scheme="gray",
                margin_bottom="0.5em",
            ),
            rx.text_area(
                placeholder="Pegá acá el equipo exportado de Showdown...",
                value=PokemonState.import_text,
                on_change=PokemonState.set_import_text,
                width="100%",
                height="260px",
            ),
            rx.cond(
                PokemonState.has_import_errors,
                rx.callout(
                    "No se pudo reconocer: " + PokemonState.import_errors_text,
                    color_scheme="red",
                    size="1",
                    margin_top="0.5em",
                ),
            ),
            rx.hstack(
                rx.dialog.close(
                    rx.button(
                        "Cancelar",
                        on_click=PokemonState.close_import,
                        variant="soft",
                        color_scheme="gray",
                    ),
                ),
                rx.button("Importar", on_click=PokemonState.apply_import),
                spacing="3",
                margin_top="0.75em",
                justify="end",
                width="100%",
            ),
        ),
        open=PokemonState.import_open,
    )


def save_team_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Guardar equipo"),
            rx.text(
                "Guarda tu equipo actual (con Speed EVs, naturaleza y "
                "los toggles de Scarf/PAR/Ability/Mega) para volver a "
                "cargarlo más adelante. Necesitás las 6 casillas llenas.",
                size="1",
                color_scheme="gray",
                margin_bottom="0.5em",
            ),
            rx.input(
                placeholder="Nombre del equipo",
                value=PokemonState.save_team_name,
                on_change=PokemonState.set_save_team_name,
                width="100%",
            ),
            rx.cond(
                PokemonState.save_team_error != "",
                rx.callout(
                    PokemonState.save_team_error,
                    color_scheme="red",
                    size="1",
                    margin_top="0.5em",
                ),
            ),
            rx.hstack(
                rx.dialog.close(
                    rx.button(
                        "Cancelar",
                        on_click=PokemonState.close_save_team,
                        variant="soft",
                        color_scheme="gray",
                    ),
                ),
                rx.button("Guardar", on_click=PokemonState.save_my_team),
                spacing="3",
                margin_top="0.75em",
                justify="end",
                width="100%",
            ),
        ),
        open=PokemonState.save_team_open,
    )


def saved_team_row(name: rx.Var) -> rx.Component:
    return rx.hstack(
        rx.text(name, size="2"),
        rx.spacer(),
        rx.button(
            "Cargar",
            size="1",
            variant="soft",
            on_click=PokemonState.load_saved_team(name),
        ),
        rx.button(
            "×",
            size="1",
            color_scheme="red",
            variant="soft",
            on_click=PokemonState.delete_saved_team(name),
        ),
        width="100%",
        align="center",
        spacing="2",
    )


def saved_teams_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Equipos guardados"),
            rx.cond(
                PokemonState.has_saved_teams,
                rx.vstack(
                    rx.foreach(PokemonState.saved_team_names, saved_team_row),
                    spacing="2",
                    width="100%",
                ),
                rx.text(
                    "Todavía no guardaste ningún equipo.",
                    size="1",
                    color_scheme="gray",
                ),
            ),
            rx.hstack(
                rx.dialog.close(
                    rx.button(
                        "Cerrar",
                        on_click=PokemonState.close_saved_teams,
                        variant="soft",
                        color_scheme="gray",
                    ),
                ),
                margin_top="0.75em",
                justify="end",
                width="100%",
            ),
        ),
        open=PokemonState.saved_teams_open,
    )


def save_matchup_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Guardar matchup"),
            rx.text(
                "Guarda tu equipo y el del rival (6 Pokémon de cada "
                "lado) junto con el resultado en el historial de "
                "matchups. Necesitás los dos equipos completos (6/6).",
                size="1",
                color_scheme="gray",
                margin_bottom="0.75em",
            ),
            rx.cond(
                PokemonState.save_matchup_error != "",
                rx.callout(
                    PokemonState.save_matchup_error,
                    color_scheme="red",
                    size="1",
                    margin_bottom="0.75em",
                ),
            ),
            rx.hstack(
                rx.button(
                    "🏆 Victoria",
                    on_click=PokemonState.save_matchup_result("Victoria"),
                    color_scheme="green",
                    width="50%",
                ),
                rx.button(
                    "💀 Derrota",
                    on_click=PokemonState.save_matchup_result("Derrota"),
                    color_scheme="red",
                    width="50%",
                ),
                spacing="3",
                width="100%",
                margin_bottom="0.75em",
            ),
            rx.dialog.close(
                rx.button(
                    "Cancelar",
                    on_click=PokemonState.close_save_matchup,
                    variant="soft",
                    color_scheme="gray",
                    width="100%",
                ),
            ),
        ),
        open=PokemonState.save_matchup_open,
    )


def match_history_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Historial de matchups"),
            rx.text(
                f"Se guarda en {MATCHUP_LOG_PATH}",
                size="1",
                color_scheme="gray",
                margin_bottom="0.5em",
            ),
            rx.cond(
                PokemonState.match_history_error != "",
                rx.callout(
                    PokemonState.match_history_error,
                    color_scheme="red",
                    size="1",
                    margin_bottom="0.5em",
                ),
            ),
            rx.cond(
                PokemonState.match_history,
                rx.scroll_area(
                    rx.vstack(
                        rx.foreach(
                            PokemonState.match_history,
                            lambda row: rx.text(row, size="1"),
                        ),
                        spacing="2",
                        width="100%",
                    ),
                    height="300px",
                ),
                rx.text(
                    "Todavía no guardaste ningún matchup.",
                    size="1",
                    color_scheme="gray",
                ),
            ),
            rx.dialog.close(
                rx.button(
                    "Cerrar",
                    on_click=PokemonState.close_match_history,
                    variant="soft",
                    color_scheme="gray",
                    margin_top="0.75em",
                    width="100%",
                ),
            ),
        ),
        open=PokemonState.match_history_open,
    )


def index() -> rx.Component:
    return rx.box(
        rx.hstack(
            # --- Columna Izquierda: Equipos ---
            rx.vstack(
                rx.box(
                    rx.hstack(
                        rx.heading("Your team", size="4", font_family="'Montserrat', sans-serif"),
                        rx.spacer(),
                        rx.button(
                            rx.icon(tag="clipboard-paste", size=14),
                            rx.text("Import"),
                            on_click=PokemonState.open_import("my"),
                            size="1",
                            variant="soft",
                        ),
                        rx.button(
                            rx.icon(tag="save", size=14),
                            rx.text("Guardar"),
                            on_click=PokemonState.open_save_team,
                            size="1",
                            variant="soft",
                        ),
                        rx.button(
                            rx.icon(tag="folder-open", size=14),
                            rx.text("Cargar"),
                            on_click=PokemonState.open_saved_teams,
                            size="1",
                            variant="soft",
                        ),
                        width="100%",
                        align="center",
                        wrap="wrap",
                    ),
                    team_grid(PokemonState.my_team, "my"),
                    rx.cond(
                        PokemonState.my_complete,
                        rx.text(
                            "Tu equipo está completo: hacé click en hasta 4 para analizarlos →",
                            size="1",
                            color_scheme="green",
                        ),
                    ),
                    style=MY_PANEL_STYLE,
                ),
                rx.box(
                    rx.heading("Rival team", size="4", font_family="'Montserrat', sans-serif"),
                    team_grid(PokemonState.rival_team, "rival"),
                    rx.cond(
                        PokemonState.rival_complete,
                        rx.text(
                            "Equipo rival completo: hacé click en hasta 4 para analizarlos →",
                            size="1",
                            color_scheme="green",
                        ),
                    ),
                    style=RIVAL_PANEL_STYLE,
                ),
                # "Save matchup" abre el diálogo Victoria/Derrota y
                # agrega una fila al Excel de historial (mi equipo /
                # equipo rival / resultado); "Historial" muestra lo
                # guardado hasta ahora.
                rx.vstack(
                    rx.button(
                        rx.icon(tag="save", size=14),
                        rx.text("Save matchup"),
                        on_click=PokemonState.open_save_matchup,
                        width="100%",
                        color_scheme="green",
                        variant="soft",
                    ),
                    rx.button(
                        rx.icon(tag="history", size=14),
                        rx.text("Historial"),
                        on_click=PokemonState.open_match_history,
                        width="100%",
                        color_scheme="gray",
                        variant="soft",
                    ),
                    rx.cond(
                        PokemonState.matchup_saved,
                        rx.text(
                            "Matchup guardado (" + PokemonState.last_matchup_result + ") ✓",
                            size="1",
                            color_scheme="green",
                        ),
                    ),
                    width="100%",
                    spacing="2",
                ),
                width="30%",
                padding="2em",
                align="start",
                spacing="4",
            ),

            # --- Columna Derecha: Stats (Condicional, separada por equipo) ---
            rx.cond(
                PokemonState.has_active_slots,
                rx.vstack(
                    # Trick Room es GLOBAL (afecta a los dos equipos a la
                    # vez invirtiendo el orden de movimiento), por eso va
                    # arriba de todo y no repetido por equipo como Tailwind.
                    rx.hstack(
                        rx.spacer(),
                        rx.button(
                            rx.icon(tag="arrow-down-up", size=14),
                            rx.text("Trick Room"),
                            on_click=PokemonState.toggle_trick_room,
                            variant=rx.cond(PokemonState.trick_room, "solid", "outline"),
                            color_scheme=rx.cond(PokemonState.trick_room, "pink", "gray"),
                            size="1",
                        ),
                        width="100%",
                    ),
                    rx.cond(
                        PokemonState.has_my_active,
                        rx.vstack(
                            rx.hstack(
                                rx.heading("Tu equipo", size="3", font_family="'Montserrat', sans-serif"),
                                rx.spacer(),
                                rx.button(
                                    rx.icon(tag="wind", size=14),
                                    rx.text("Tailwind"),
                                    on_click=PokemonState.toggle_my_tailwind,
                                    variant=rx.cond(PokemonState.my_tailwind, "solid", "outline"),
                                    color_scheme=rx.cond(PokemonState.my_tailwind, "teal", "gray"),
                                    size="1",
                                ),
                                width="100%",
                                align="center",
                            ),
                            rx.grid(
                                rx.foreach(PokemonState.my_active_slots, stats_card),
                                columns="2",
                                spacing="4",
                                width="100%",
                            ),
                            width="100%",
                            align="start",
                            spacing="2",
                        ),
                    ),
                    rx.cond(
                        PokemonState.show_divider,
                        rx.divider(margin_y="1.5em"),
                    ),
                    rx.cond(
                        PokemonState.has_rival_active,
                        rx.vstack(
                            rx.hstack(
                                rx.heading("Rival", size="3", font_family="'Montserrat', sans-serif"),
                                rx.spacer(),
                                rx.button(
                                    rx.icon(tag="wind", size=14),
                                    rx.text("Tailwind"),
                                    on_click=PokemonState.toggle_rival_tailwind,
                                    variant=rx.cond(PokemonState.rival_tailwind, "solid", "outline"),
                                    color_scheme=rx.cond(PokemonState.rival_tailwind, "teal", "gray"),
                                    size="1",
                                ),
                                width="100%",
                                align="center",
                            ),
                            rx.grid(
                                rx.foreach(PokemonState.rival_active_slots, stats_card),
                                columns="2",
                                spacing="4",
                                width="100%",
                            ),
                            width="100%",
                            align="start",
                            spacing="2",
                        ),
                    ),
                    width="70%",
                    align="start",
                ),
                rx.center(
                    rx.text(
                        "Completá cada equipo (6/6) y elegí hasta 4 de cada uno "
                        "para ver sus stats"
                    ),
                    width="70%",
                    style=PANEL_STYLE,
                ),
            ),

            # --- Diálogo de Selección ---
            selector_dialog(),
            import_dialog(),
            save_team_dialog(),
            saved_teams_dialog(),
            save_matchup_dialog(),
            match_history_dialog(),

            padding="2em",
            spacing="8",
            width="100%",
            align="start",
        ),
        # Botón de tema: fijo en la esquina inferior derecha, por encima de
        # todo. Solo alterna el FONDO de la página (PAGE_BACKGROUND_*) --
        # a propósito no toca los paneles ni el resto de los colores.
        rx.icon_button(
            rx.cond(
                PokemonState.light_theme,
                rx.icon(tag="moon", size=18),
                rx.icon(tag="sun", size=18),
            ),
            on_click=PokemonState.toggle_theme,
            variant="soft",
            color_scheme="gray",
            radius="full",
            size="3",
            style={
                "position": "fixed",
                "bottom": "20px",
                "right": "20px",
                "z-index": "50",
                "box-shadow": "0 2px 10px rgba(0, 0, 0, 0.35)",
            },
        ),
        background_image=rx.cond(
            PokemonState.light_theme,
            PAGE_BACKGROUND_LAYERS_LIGHT,
            PAGE_BACKGROUND_LAYERS_DARK,
        ),
        background_size="780px 780px, cover, cover",
        background_position="center 42%, center, center",
        background_repeat="no-repeat, no-repeat, no-repeat",
        background_attachment="fixed, fixed, fixed",
        min_height="100vh",
        width="100%",
    )


app = rx.App(
    stylesheets=["/fonts.css"],
)
app.add_page(index)
