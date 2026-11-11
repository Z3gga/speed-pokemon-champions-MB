import reflex as rx
import pandas as pd
from typing import List, Dict, TypedDict

TEAM_SIZE = 6


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
# Carga del CSV UNA SOLA VEZ a nivel de módulo.
# El código original leía el CSV dentro de un @rx.var cada vez que Reflex
# recalculaba esa propiedad (cada render). Eso es I/O de disco innecesario
# y, si el CSV crece, puede volverse un cuello de botella real de latencia.
# ---------------------------------------------------------------------------
def _load_pokemon_data() -> List[Dict[str, str]]:
    """
    Carga nombre + imagen del CSV. Devuelve una lista de dicts en vez de
    solo nombres, para poder mostrar el sprite en la UI.

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


POKEMON_DATA = _load_pokemon_data()
POKEMON_NAMES = [p["name"] for p in POKEMON_DATA]
# Mapa nombre -> url de imagen, para pintar el sprite en los botones del equipo
POKEMON_IMAGES: Dict[str, str] = {p["name"]: p["image"] for p in POKEMON_DATA}


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

    @rx.var(cache=True)
    def pokemon_images(self) -> Dict[str, str]:
        return POKEMON_IMAGES

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

    def set_speed_ev(self, global_index: int, value: List[int]):
        self.speed_evs[global_index] = value[0]

    def set_buff(self, global_index: int, value: List[int]):
        self.buffs[global_index] = value[0]

    def toggle_scarf(self, global_index: int):
        self.scarf[global_index] = not self.scarf[global_index]

    def toggle_para(self, global_index: int):
        self.para[global_index] = not self.para[global_index]


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
    return rx.box(
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
                    "Velocidad: WIP por ahora",
                    color="#a855f7",
                    font_weight="bold",
                    size="2",
                ),
                rx.text("Speed EVs", size="2", color_scheme="gray"),
                rx.slider(
                    default_value=[0],
                    min=0,
                    max=252,
                    step=4,
                    disabled=True,
                    color_scheme="gray",
                ),
                rx.text("Buffs", size="2", color_scheme="gray"),
                rx.slider(
                    default_value=[0],
                    min=-6,
                    max=6,
                    step=1,
                    on_change=lambda v: PokemonState.set_buff(idx, v),
                    accent_color="blue",
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
