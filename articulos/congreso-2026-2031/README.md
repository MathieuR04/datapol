# Cómo vota el Congreso 2026-2031

Tablero de las votaciones nominales del Pleno del **Senado** (60) y la **Cámara de
Diputados** (130): mapa 2×2 de posiciones por parlamentario y por bancada, la línea
oficialismo/oposición con sus «bisagras» y «cruzados», cada votación por bancada y
escaño, y una ficha por parlamentario con foto oficial.

## Actualizar

```sh
python3 update.py            # todo, y commit + push si algo cambió
python3 update.py --no-push  # todo, sin tocar git
```

Cada paso es incremental: sólo baja PDFs nuevos, sólo hace OCR de PDFs nuevos o
re-publicados (caché por sha256) y sólo baja fotos que falten. Una corrida sin
sesiones nuevas tarda segundos; cada PDF nuevo, ~1 min por cada 10 páginas.

Requisitos (una vez): `brew install poppler tesseract`,
`pip3 install opencv-python pytesseract pandas scipy pillow certifi`, y el modelo
`tessdata/spa.traineddata` (tessdata_best; está gitignoreado — copiarlo de
`../congressional_votes_parsing/tessdata/`).

## Piezas

| script | hace |
|---|---|
| `scrape_sesiones.py` | lee la tabla de sesiones de cada cámara y baja lo que haya en la columna **«Votaciones y Asistencias»** (por encabezado, no por nombre de archivo: los nombres cambian sin aviso) |
| `roster.py` | padrón oficial desde la API WordPress de cada cámara (`/wp-json/wp/v2/diputado`, `/senador`): nombre, bancada, distrito, foto |
| `parser.py` | OCR de cada página (heredado del parser 2021, ver su docstring) y asignación de cada fila al padrón oficial |
| `parse_all.py` | corre el parser sobre el manifiesto y consolida `data/votos.csv` + `data/paginas.csv` |
| `estimate.py` | puntos ideales (embedding espectral, Golub-Jackson), línea oficialismo/oposición, métricas por miembro |
| `build_web.py` | `web/<camara>.json` para el tablero |
| `config.py` | **decisiones editoriales**: qué bancadas son oficialismo/oposición |

## Decisiones y hallazgos que no se ven en el código

- **Oficialismo = FP + RP; oposición = PCO, PBG, AN, JP** (decisión 2026-09-27, en
  `config.py`). Si cambia la correlación, se edita ahí y se corre `update.py`.
- **Validación por bancada.** Cada acta trae un cuadro Si/No/Abst por bancada; es el
  control principal porque el sello de Relatoría suele tapar el cuadro de totales en
  Diputados. Una página sólo cuenta como `ok` si cuadra bancada por bancada.
- **El cuadro de totales puede decir lo *anunciado*, no lo registrado.** 13/08/2026
  (Diputados): «se anunciaron 115 votos a favor, habiéndose registrado 120». El
  tablero usa lo registrado y **no** muestra la observación: esas votaciones van a
  `data/revisar.csv` (lista interna para rehacer a mano, junto con las páginas que no
  cuadren), que `update.py` avisa al final de cada corrida.
- **Colores:** los parlamentarios y bancadas se pintan con los colores de partido de
  congresoperu2026.com (`--p-FP`, … en `index.html`); en los votos, Sí verde oliva y No rojo oscuro.
- **Constancias** («deja constancia del voto a favor de…») se aplican sobre el voto
  de la tabla; el conteo de validación es el de *antes* de aplicarlas, porque así
  está impreso.
- **Fuera por ahora:** las páginas de tabla con ✓ («VOTACIÓN NOMINAL», votación
  manual de Diputados del 05/08/2026). Son pocas y procedimentales; el parser las
  marca `TABLA_CHECK`.
- **Pocas votaciones al inicio:** con pocas votaciones disputadas las posiciones son
  preliminares; el tablero lo advierte solo (umbral: 30 disputadas).
