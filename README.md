# Speed Champions

Aplicación web hecha con [Reflex](https://reflex.dev) para analizar **speed tiers** y enfrentamientos (matchups) en Pokémon Champions: calcula velocidades según EVs, naturaleza, Scarf, Tailwind, parálisis, Mega Evolución y Trick Room, y permite guardar tu equipo, el del rival y un historial de matchups.

## Requisitos

- Python 3.11 o superior
- Git

## Instalación y ejecución

```bash
git clone https://github.com/Z3gga/speed-pokemon-champions-MB.git
cd speed-pokemon-champions-MB

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate

pip install -r requirements.txt
reflex run
```

La app queda disponible en http://localhost:3000.

## Estructura

```
rxconfig.py          # Configuración de Reflex (app_name = "es")
es/es.py             # Aplicación principal
assets/              # CSV de speed tiers, sprites, íconos y fuentes
data/                # Historial de matchups (matchup_history.xlsx)
requirements.txt
```

## Créditos

Pokémon es marca de Nintendo / Creatures Inc. / GAME FREAK inc. Este es un proyecto de fans sin fines de lucro y no está afiliado a ellos.
