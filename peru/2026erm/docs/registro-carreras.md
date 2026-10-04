# Fase 01 — Registro de carreras y distritos

Construido el 12 de agosto de 2026 desde el registro de candidaturas del JNE del 11
de agosto, más las tablas de referencia.

```
uv run python scripts/build_registro_carreras.py
```

Salida, versionada en git: `data/reference/distritos.csv` y
`data/reference/carreras.csv`. El script **falla con código 1 si algún cuadre no
da**, así que no puede producir una tabla mal sin avisar.

## Cuadres — los 15 dan exacto

```
distritos
  filas de distritos.csv                        1,892
  cercados (sin carrera distrital)                196
  distritos con carrera distrital               1,696
  Lima Metropolitana sin gobernador                43
  Lima Metropolitana sin consejero                 43
  Callao con consejero distrital                    7

carreras
  gobernador (01)                                  25
  consejero (02)                                  201
  alcalde provincial (03)                         196
  alcalde distrital (04)                        1,696
  total                                         2,118
  race_id duplicados                                0

escaños de consejeros
  Σ consejeros (Res. 0001-2026-JNE)               364
  filas de la referencia                          201
```

Verificación cruzada independiente: las **1,026 carreras** que hoy tienen candidatos
inscritos existen todas en `carreras.csv`. Cero huérfanas.

## Corrección a la spec: son 1,892 distritos, no 1,896

La spec 01 pide 1,896 distritos, y su propio cuadre no cierra: 1,896 − 196 capitales
= 1,700, pero declara 1,696 carreras distritales. Sobran 4.

El número correcto es **1,892**, confirmado por el operador y por la aritmética del
registro: 1,696 distritos con carrera + 196 cercados = 1,892, sin residuo.

## La regla del cercado, y sus cuatro excepciones

Cada provincia tiene un distrito **cercado** que no elige alcalde distrital, porque
lo gobierna la municipalidad provincial. Su ubigeo es `{ubigeo_provincia[:4]}01` en
**192 de 196** provincias — verificado: ese ubigeo no aparece nunca entre los que sí
tienen carrera distrital.

En cuatro provincias el `01` es un distrito común y el cercado está en otro número.
En cada una hay **exactamente un hueco** en la numeración, y es el cercado:

| Provincia | `{prov}01` resulta ser | Cercado real |
|---|---|---|
| AMAZONAS / BAGUA | LA PECA | `010205` |
| ANCASH / OCROS | ACAS | `022007` |
| HUANCAVELICA / HUAYTARA | AYAVI | `080604` |
| HUANUCO / PUERTO INCA | HONORIA | `090802` |

En las cuatro, ningún distrito con carrera lleva el nombre de la provincia, lo que es
coherente con que el ausente sea el homónimo. Declaradas como datos en
`data/reference/cercados_excepcion.csv`, no como lógica.

Si en el futuro un cercado colisiona con un distrito que sí tiene carrera, el script
lo reporta como aviso en vez de producir una tabla silenciosamente mal.

## Excepciones aplicadas, una por una

**Lima Metropolitana (`1401xx`) — 43 distritos.** `race_gobernador` y
`race_consejero` en nulo: no elige ni gobernador ni consejeros. Sí participa en la
carrera provincial `03-140100`, que es la alcaldía de Lima. El cuadre de 43 salió
exacto contra lo que declara la spec.

**Callao (`2401xx`) — 7 distritos.** `race_consejero = 02-{ubigeo_distrito}`, no
`02-240100`: en el Callao la circunscripción de consejero es el distrito. Son las 7
que faltaban para que 194 provincias + 7 distritos = 201 circunscripciones.

**Cercados — 196.** `race_distrital` en nulo.

**Lima provincias.** Es circunscripción regional separada de Lima Metropolitana y su
ODPE está en Huaura. En `distritos.csv` no requiere columna aparte: las 9 provincias
que no son Lima llevan su `race_gobernador = 01-140000` y su `race_consejero`
provincial con normalidad, y es Lima Metropolitana la que los tiene en nulo. La
separación queda expresada por ausencia.

## Esquema de `carreras.csv`

```
race_id, tipo, id_tipo_jne, ubigeo, nivel_circunscripcion, nombre_circunscripcion,
cargo_ejecutivo, cargo_proporcional, n_escanos, fuente_n_escanos,
umbral_primera_vuelta, tiene_segunda_vuelta, electores_habiles, n_mesas, jee, odpe,
estado
```

**`nivel_circunscripcion` es explícito, nunca derivado del tipo de elección**
(regla 9). Las carreras de consejero se reparten en 194 de nivel `provincia` y 7 de
nivel `distrito`; el tipo `02` es el mismo para ambas.

**`id_tipo_jne`**: consejero comparte el `4` (REGIONAL) con gobernador — no es un
tipo aparte para el JNE, aunque sí sea otra carrera para nosotros.

**Segunda vuelta**: solo gobernador, con umbral de 30% de válidos. Alcalde provincial
y distrital, mayoría simple y nunca segunda vuelta.

**`n_escanos`**: poblado solo para las 201 carreras de consejero, desde la
Res. 0001-2026-JNE, sumando 364. Los regidores son la fase 02.

## Lo que queda pendiente

**195 cercados sin nombre de distrito.** No tienen carrera distrital, así que no
generan filas en el registro de candidaturas y su nombre no está en ninguna fuente
disponible. El del Callao (`240101` = CALLAO) sí se resolvió, desde la tabla de
circunscripciones de consejero.

Se podría rellenar con el nombre de la provincia, pero **la convención falla**: en 16
provincias hay un distrito con carrera que ya lleva el nombre de la provincia, o sea
que ahí el cercado se llama de otro modo. Rellenar por convención es exactamente el
error que en el Callao habría asignado mal cuatro circunscripciones. Quedan en nulo
hasta tener el catálogo de ubigeos de la ONPE (`/v1/ERM2026/ubigeos/{tipo}`, fase 04).

**`electores_habiles`, `n_mesas`, `jee`, `odpe`** — vacíos. Salen de la ONPE, fase 04,
bloqueada hasta que abra el servicio.

**`n_escanos` de regidores** — resuelto en la misma corrida, por conteo de
candidatos. Ver `docs/escanos.md`. Queda confirmarlo contra la Res. 0847-2025-JNE
cuando el operador entregue el PDF.

**Cuadre de 13,148 autoridades** — **cierra exacto.** Ver `docs/escanos.md`.
