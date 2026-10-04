# Fase 04 — Maestro de mesas

*12 de setiembre de 2026.* `scripts/build_mesas.py` → `data/processed/mesas.csv`
(89,935 filas) y `data/reference/locales.csv` (10,180).

## De dónde salió

La respuesta de la ONPE al **Expediente N.º 292325-2026** (SAIP, 25 de agosto),
archivada en `data/raw/onpe_saip_292325_2026/`. El archivo útil es
`GOECOR/LOCALES ODPE UBIGEO Y  OTROS.xlsx`: un local por fila, con ubigeo, ODPE,
número de mesas y electores hábiles, al corte del 16 de julio de 2026.

**Esto cierra los dos bloqueos que la spec declaraba.** Ya no hace falta `n_mesas`
por distrito —viene en la fuente— ni minar la cookie `aws-waf-token` de
`consultaelectoral.onpe.gob.pe`, que existía solo para sacar mesas y locales de a
una consulta por DNI. La fase se resolvió sin una sola petición de red.

## Cuadres

| | |
|---|---|
| Locales | 10,180 |
| ODPEs | 125 |
| Mesas | **89,935** |
| Distritos cubiertos | **1,892 de 1,892**, sin huecos ni sobrantes |
| Electores municipales | 26,314,724 = 26,314,648 del padrón + 76 extranjeros |

Los dos rangos de numeración salen de la columna `LOCALIDADES CON MSI`, y cuadran
al dígito contra las cifras que la spec ya daba por establecidas:

- 8,172 locales **sin** MSI → **84,992** mesas = rango `000001`–`084992`.
- 2,008 locales **con** MSI → **4,943** mesas = rango `900001`–`904943`.

## Cómo se asigna cada mesa a su distrito

### Rango normal: verificado al 100%

Los bloques van en orden ascendente de ubigeo, uno contiguo por distrito. La
reconstrucción es una suma acumulada, sin ninguna consulta.

**La validación es contra dos procesos reales, no contra sí misma.**

| Proceso | Mesas del rango normal | Reconstruidas bien |
|---|---|---|
| ERM 2022 | 80,420 | **80,420 — 100.0000%** |
| EG 2026 | 85,520 | **85,520 — 100.0000%** |

Ni un solo error en ninguno de los dos, y la propiedad estructural se sostiene:
un bloque contiguo por distrito, un único tramo ascendente en todo el rango.
EG 2026 importa especialmente porque es del mismo año y la misma ONPE, cinco meses
antes de las municipales.

En 2026 la última mesa normal, la 084992, cae en **Purús (250401)**, que es lo que
la spec anticipaba.

### Rango especial: orden por ODPE, validado al 99.94%

Aquí el ubigeo solo no alcanza, y conviene decir exactamente por qué, porque es la
hipótesis natural y es falsa. Ordenando por ubigeo **solo los distritos que tienen
mesas 900k** —con el oráculo perfecto de cuáles son y cuántas, extraído de los
propios datos— el acierto es del **35.2% en ERM 2022** y de apenas el **22.0% en
EG 2026**. La secuencia real de 2022 empieza así:

```
010106, 010109, 010403, 010409, 010413, 010414, 010419, 010420,
010503, 010509, 010512, 010311, 010312, 010201, ...
```

Rodríguez de Mendoza (0105) antes que Bongará (0103) y que Bagua (0102). El rango
ni siquiera mantiene contiguos los departamentos: 27 tramos para 24.

Pero hay estructura. Cada distrito ocupa **un solo bloque contiguo** —799 bloques
para 799 distritos en EG 2026— y hay apenas 48 tramos ascendentes, con los cortes
cayendo dentro de cada departamento. Es la firma de un orden por ODPE. ERM 2022 no
traía el mapa de ODPE; el SAIP de 2026 sí, así que estas mesas se ordenan por
`(odpe, ubigeo_distrito, local_id)`.

**Y eso sí se pudo medir contra verdad de campo.** Aplicando el mapa de ODPE del
SAIP de ERM 2026 al orden observado de las 4,703 mesas 900k de EG 2026:

| Orden | Aciertos |
|---|---|
| `(odpe, ubigeo)` | **4,700 / 4,703 — 99.94%** |
| solo `ubigeo` | 1,036 / 4,703 — 22.0% |

Tres mesas mal de 4,703, y con el mapa de ODPE de un proceso distinto; contra el
suyo propio debería ir mejor. Sale marcado `metodo=orden_odpe`, `confianza=alta`,
distinguible del rango normal (`frontera_ubigeo`, `confianza=exacta`) por si algo
río abajo quiere solo lo exacto. Afecta a 809 distritos y se reconfirma solo el 4
de octubre, cuando cada acta de la API en vivo traiga su `codigoLocalVotacion`.

## Criterios de aceptación de la spec

| Criterio | Estado |
|---|---|
| `mesas.csv` cubre las 89,935 con `ubigeo_distrito` | **Cumplido**, 100% asignado |
| Rangos contiguos, sin solapes, suman 89,935 | **Cumplido**, con test |
| Toda mesa asignable a sus carreras | **Cumplido**: las 89,935 tienen `race_provincial` |
| `local_id` poblado o marcado pendiente | **Cumplido** en los dos rangos |
| Ningún archivo en git con DNI ↔ mesa | **Cumplido**: no se usó ni una consulta por DNI |

32 tests en `tests/test_mesas.py` y `tests/test_candidatos_inscritos.py`.

## Lo que cambia río abajo

`mesas.csv` trae ya las cuatro columnas de carrera, así que el forecaster hace el
join directo. Reparto de mesas por tipo de carrera, rango normal:

| | mesas | carreras |
|---|---|---|
| Gobernador | 58,797 | 25 |
| Consejero regional | 58,797 | 201 |
| Alcalde provincial | 84,992 | 196 |
| Alcalde distrital | 62,972 | 1,696 |
