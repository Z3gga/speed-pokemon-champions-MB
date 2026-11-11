import reflex as rx
import pandas as pd
from typing import List, Dict, TypedDict

TEAM_SIZE = 6

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
    "background": "rgba(103, 76, 238, 0.45)",      # azul
    "border": "2px solid rgba(20, 23, 71, 1)",
    "box-shadow": "0 0 0 2px rgba(255, 255, 255, 0)",
}
RIVAL_PANEL_STYLE = {
    **PANEL_STYLE,
    "background": "rgba(167, 24, 78, 0.45)",      # rosa
    "border": "2px solid rgba(20, 23, 71, 1)",
    "box-shadow": "0 0 0 2px rgba(255, 255, 255, 0)",
}


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
    ability: str = "", ability_active: bool = False,
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
        3. Se aplican los modificadores de item/habilidad/estado combinados
           multiplicando antes de un único floor final:
           - Choice Scarf: ×1.5
           - Habilidad (si el botón está activo): x2, o x1.5 si es Quick Feet
           - Parálisis (gens modernas): ×0.5

    `nature` es "pos" (+10%), "neg" (-10%) o "" (neutra, sin selección).
    `ability` es el nombre de la habilidad relevante para Speed de ese
    Pokémon ("" si no tiene ninguna); `ability_active` es el toggle del
    botón en la UI, que solo aparece cuando `ability` no está vacío.
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
    def my_complete(self) -> bool:
        return all(name != "" for name in self.my_team)

    @rx.var(cache=True)
    def rival_complete(self) -> bool:
        return all(name != "" for name in self.rival_team)

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
    def show_divider(self) -> bool:
        """La línea divisoria entre 'tu equipo' y 'rival' en el panel de
        stats solo aparece si hay elementos marcados de AMBOS lados."""
        return self.has_my_active and self.has_rival_active

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

    def save_matchup(self):
        # WIP: por ahora el panel de stats se arma solo con las
        # selecciones actuales (ver `active_slots`), no hace falta un
        # paso de "guardado" explícito. Este botón queda reservado para
        # una futura función de persistencia del matchup.
        self.matchup_saved = True

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
            rx.text(team[index], size="1", text_align="center"),
            spacing="1",
            align="center",
        ),
        rx.text("+", size="5"),
    )

    # Resalte visual: marca en verde los Pokémon elegidos para el panel de
    # stats (solo tiene efecto una vez que ese equipo está completo, que es
    # cuando `my_selected` / `rival_selected` empiezan a importar).
    selected_var = PokemonState.rival_selected[index] if side == "rival" else PokemonState.my_selected[index]
    slot_style = rx.cond(
        selected_var,
        {**PANEL_STYLE, "border": "2px solid #22c55e", "padding": "0"},
        {**PANEL_STYLE, "padding": "0"},
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
    card_style = rx.cond(slot["side"] == "my", MY_PANEL_STYLE, RIVAL_PANEL_STYLE)

    return rx.box(
        buff_stepper,
        rx.hstack(
            rx.image(
                src=PokemonState.pokemon_images[effective_name],
                width="110px",
                height="110px",
            ),
            rx.vstack(
                rx.hstack(
                    rx.badge(slot["side"]),
                    rx.text(effective_name, font_weight="bold", size="4"),
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
                        rx.icon(tag="shirt", size=16),
                        rx.text("Scarf"),
                        on_click=PokemonState.toggle_scarf(idx),
                        variant=rx.cond(PokemonState.scarf[idx], "solid", "outline"),
                        color_scheme=rx.cond(PokemonState.scarf[idx], "blue", "gray"),
                        size="2",
                    ),
                    rx.button(
                        rx.icon(tag="zap", size=16),
                        rx.text("PAR"),
                        on_click=PokemonState.toggle_para(idx),
                        variant=rx.cond(PokemonState.para[idx], "solid", "outline"),
                        color_scheme=rx.cond(PokemonState.para[idx], "orange", "gray"),
                        size="2",
                    ),
                    rx.cond(
                        PokemonState.pokemon_ability[effective_name] != "",
                        rx.button(
                            rx.icon(tag="sparkles", size=16),
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
                                rx.icon(tag="gem", size=16),
                                rx.text("Mega"),
                                on_click=PokemonState.toggle_mega(idx),
                                variant=rx.cond(PokemonState.mega_active[idx], "solid", "outline"),
                                color_scheme=rx.cond(PokemonState.mega_active[idx], "amber", "gray"),
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
                                                "amber",
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


def index() -> rx.Component:
    return rx.box(
        rx.hstack(
            # --- Columna Izquierda: Equipos ---
            rx.vstack(
                rx.box(
                    rx.heading("Your team", size="4"),
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
                    rx.heading("Rival team", size="4"),
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
                # WIP: sin funcionalidad todavía. El panel de la derecha ya se
                # arma automáticamente con `my_active_slots` / `rival_active_slots`,
                # no depende de este botón.
                rx.button(
                    "Save matchup (WIP)",
                    disabled=True,
                    width="100%",
                    color_scheme="gray",
                    variant="soft",
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
                    rx.cond(
                        PokemonState.has_my_active,
                        rx.vstack(
                            rx.heading("Tu equipo", size="3"),
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
                            rx.heading("Rival", size="3"),
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

            padding="2em",
            spacing="8",
            width="100%",
            align="start",
        ),
        background_image="url('/fondo.jpeg')",
        background_size="cover",
        background_position="center",
        background_repeat="no-repeat",
        background_attachment="fixed",
        min_height="100vh",
        width="100%",
    )


app = rx.App()
app.add_page(index)
