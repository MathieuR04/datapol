"""Decisiones editoriales del tablero, en un solo lugar.

Si una bancada cambia de lado, se edita acá y se corre `python3 update.py`.
"""

# Línea oficialismo / oposición (definida por bancada, decisión editorial
# del 2026-09-27). Los «bisagra» son los miembros más cercanos al corte entre
# ambos bloques en la dimensión 1.
OFICIALISMO = {"FP", "RP"}
OPOSICION = {"PCO", "PBG", "AN", "JP"}

# Variantes de código de bancada impresas en los PDF → código canónico.
ALIAS_GRUPO = {"OBRAS": "PCO"}

TAMANO_CAMARA = {"diputados": 130, "senado": 60}
