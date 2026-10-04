"""Carga un script numerado (`02b_scrape_mesas.py`) como módulo.

Un nombre que empieza con dígito no se puede importar con `import`, y los
scripts se numeran por etapa a propósito (ver `scripts/README.md`).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
for p in (RAIZ / "src", RAIZ / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def carga(nombre: str):
    if nombre in sys.modules:
        return sys.modules[nombre]
    spec = importlib.util.spec_from_file_location(nombre, RAIZ / "scripts" / f"{nombre}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = mod
    spec.loader.exec_module(mod)
    return mod
