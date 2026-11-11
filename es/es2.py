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
# Carga de los CSVs UNA SOLA VEZ a nivel de módulo (I/O de disco cacheado,
# no dentro de un @rx.var que se recalcularía en cada render).
# ---------------------------------------------------------------------------
def _load_pokemon_data() -> List[Dict[str, str]]:
    """
    Carga nombre + imagen del roster (`assets/pokemon.csv`). Devuelve una
    lista de dicts en vez de solo nombres, para poder mostrar el sprite en
    la UI.

    Nota: el CSV tiene las columnas `Nombre` e `Imagen` (con mayúscula
    inicial). El bug anterior buscaba `df["nombre"]` en minúscula, lo cual
    tira un KeyError silencioso (atrapado por el `except Exception`) y por
    eso siempre caía al fallback sin avisar.
    """
    try:
        df = pd.read_csv("assets/pokemon.csv")
        return [
            {"name": row["Nombre"], "image": row["Imagen"]}
            for _, row in df.iterrows()
        ]
    except Exception as e:
        print(f"[PokemonState] No se pudo cargar assets/pokemon.csv: {e!r}")
        return [
            {"name": "Froslass", "image": ""},
            {"name": "Archaludon", "image": ""},
            {"name": "Carga tu CSV en assets/pokemon.csv", "image": ""},
        ]


SPEED_TIERS_PATH = "assets/speed_tiers_regb.csv"


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


def _load_speed_tiers() -> Dict[str, int]:
    """
    Carga el chart de referencia `assets/speed_tiers_regb.csv` (formato:
    `#, Pokémon, Base, No Invest, Max+, Max, Min, Scarf/+1, Tailwind/+2,
    Paralyzed`) y devuelve un dict nombre-normalizado -> Base Speed.

    Se usa como fuente AUTOMÁTICA del Base Speed: se cruza por nombre
    contra `assets/pokemon.csv`, así el usuario no tiene que cargar la
    velocidad a mano por cada Pokémon.

    La columna de nombre se referencia por posición (`df.columns[1]`) y no
    por su string literal, porque ese string llega mojibake-encoded
    ("PokÃ©mon") y depender de él sería frágil.
    """
    try:
        df = pd.read_csv(SPEED_TIERS_PATH, encoding="utf-8-sig")
        name_col = df.columns[1]
        tiers: Dict[str, int] = {}
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
            tiers[name.lower()] = base
        return tiers
    except Exception as e:
        print(f"[PokemonState] No se pudo cargar {SPEED_TIERS_PATH}: {e!r}")
        return {}


POKEMON_DATA = _load_pokemon_data()
POKEMON_NAMES = [p["name"] for p in POKEMON_DATA]
# Mapa nombre -> url de imagen, para pintar el sprite en los botones del equipo
POKEMON_IMAGES: Dict[str, str] = {p["name"]: p["image"] for p in POKEMON_DATA}

SPEED_TIERS = _load_speed_tiers()

# Mapa nombre (tal como aparece en pokemon.csv) -> Base Speed, cruzando por
# nombre normalizado (sin espacios extra, case-insensitive) contra el chart
# de speed tiers. Si un Pokémon del roster no tiene match ahí, queda en 0 y
# se avisa por consola (con la lista completa) para que se pueda corregir
# el nombre en uno de los dos CSVs.
POKEMON_BASE_SPEED: Dict[str, int] = {}
_missing_speed_matches: List[str] = []
for _name in POKEMON_NAMES:
    _base = SPEED_TIERS.get(_name.strip().lower())
    if _base is None:
        _missing_speed_matches.append(_name)
        _base = 0
    POKEMON_BASE_SPEED[_name] = _base
if _missing_speed_matches:
    print(
        f"[PokemonState] Aviso: {len(_missing_speed_matches)} Pokémon de "
        f"pokemon.csv sin match de nombre en {SPEED_TIERS_PATH} "
        f"(Base Speed = 0): {_missing_speed_matches}"
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


def _calc_speed(base: int, ev: int, nature: str, stage: int, scarf: bool, para: bool) -> int:
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
        3. Se aplican los modificadores de item/estado combinados
           multiplicando antes de un único floor final:
           - Choice Scarf: ×1.5
           - Parálisis (gens modernas): ×0.5

    `nature` es "pos" (+10%), "neg" (-10%) o "" (neutra, sin selección).
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
    # Naturaleza de Speed: "" (neutra, sin elegir), "pos" (+10%), "neg" (-10%)
    nature: List[str] = [""] * (TEAM_SIZE * 2)
    # Colapsa/expande la sección de Speed EVs + Naturaleza en cada tarjeta,
    # para no mostrar tanto dato de una: arranca oculta.
    show_details: List[bool] = [False] * (TEAM_SIZE * 2)

    @rx.var(cache=True)
    def pokemon_images(self) -> Dict[str, str]:
        return POKEMON_IMAGES

    @rx.var(cache=True)
    def computed_speeds(self) -> List[int]:
        """
        Velocidad real por slot global (0-5 = my_team, 6-11 = rival_team),
        recalculada en vivo con los EVs, la naturaleza (±10%/neutra), el
        stat stage (buffs -6..+6) y los toggles de Scarf/PAR actuales.
        0 si esa casilla está vacía o el Pokémon no tiene base speed
        cargada.
        """
        speeds: List[int] = []
        for i in range(TEAM_SIZE):
            base = POKEMON_BASE_SPEED.get(self.my_team[i], 0)
            speeds.append(
                _calc_speed(
                    base, self.speed_evs[i], self.nature[i], self.buffs[i],
                    self.scarf[i], self.para[i],
                )
            )
        for i in range(TEAM_SIZE):
            gi = TEAM_SIZE + i
            base = POKEMON_BASE_SPEED.get(self.rival_team[i], 0)
            speeds.append(
                _calc_speed(
                    base, self.speed_evs[gi], self.nature[gi], self.buffs[gi],
                    self.scarf[gi], self.para[gi],
                )
            )
        return speeds

    @rx.var(cache=True)
    def filtered_pokemon_options(self) -> List[str]:
        """Lista filtrada por `search_query` (case-insensitive, substring)."""
        if not self.search_query:
            return POKEMON_NAMES
        q = self.search_query.lower()
        return [name for name in POKEMON_NAMES if q in name.lower()]

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
        {"border": "2px solid #22c55e"},
        {"border": "1px solid #333"},
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

    return rx.box(
        buff_stepper,
        rx.hstack(
            rx.image(
                src=PokemonState.pokemon_images[slot["name"]],
                width="110px",
                height="110px",
            ),
            rx.vstack(
                rx.hstack(
                    rx.badge(slot["side"]),
                    rx.text(slot["name"], font_weight="bold", size="4"),
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
                    spacing="2",
                ),
                align="start",
                spacing="2",
                width="100%",
            ),
            align="start",
            spacing="4",
        ),
        border="1px solid #333",
        padding="1em",
        border_radius="8px",
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
    return rx.hstack(
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
            ),
        ),

        # --- Diálogo de Selección ---
        selector_dialog(),

        padding="2em",
        spacing="8",
        width="100%",
    )


app = rx.App()
app.add_page(index)
