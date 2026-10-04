# Fase 00 — Inventario de fuentes locales

Corte de los datos: `erm2026_candidatos.csv` del **11 de agosto de 2026, 14:26**;
`hdv_erm2026.sqlite` del **11 de agosto de 2026, 15:52**.
Inventario levantado el **12 de agosto de 2026**.

Este documento describe el esquema **original** de las fuentes, tal como están, antes
de cualquier transformación. Es el paso 1 de `specs/00-fuentes-locales.md`.

## Acceso a las fuentes — no se copian

**Corrección a la spec.** La spec 00 dice copiar las fuentes a `2026/data/raw/` y
trabajar sobre la copia. **No se hace.** Las fuentes las actualiza a diario un flujo
ajeno a este repo, así que una copia congelada quedaría desfasada en silencio y
haría creer que se está mirando el registro de hoy. Se consultan siempre en su
dirección original, en modo lectura:

| Fuente | Tamaño | Dirección |
|---|---|---|
| Registro de candidaturas | 34 MB | `erm-2026-candidatos/data/erm2026_candidatos.csv` |
| Hojas de vida | 369 MB | `erm-2026-candidatos/data/hdv/hdv_erm2026.sqlite` |
| Organizaciones | 16 KB | `erm-2026-candidatos/data/organizaciones_erm2026.csv` |

Las direcciones están centralizadas en `src/datapol/fuentes.py`; ningún script las
escribe. El sqlite se abre con `mode=ro`.

Segunda corrección a la spec: el sqlite no está en la raíz de `data/` sino en
`data/hdv/hdv_erm2026.sqlite`. En ese mismo directorio hay un `hdv_eg2026.sqlite`
(Elecciones Generales, otro proceso) que **no** corresponde a esta fase.

---

## 1. `erm2026_candidatos.csv`

**101,617 filas × 35 columnas.** Grano: un candidato. Sin cabeceras duplicadas, sin
filas mal formadas. Todos los campos llegan como texto; los ubigeos conservan el cero
inicial y deben leerse como `str`, nunca como entero.

### Esquema

| # | Columna | Nulos | Distintos | Nota |
|---|---|---|---|---|
| 1 | `proceso_id` | 0 | 1 | Siempre `126` |
| 2 | `proceso` | 0 | 1 | `ELECCIONES REGIONALES Y MUNICIPALES 2026` |
| 3 | `tipo_eleccion_id` | 0 | 3 | `4` regional, `5` provincial, `6` distrital |
| 4 | `tipo_eleccion` | 0 | 3 | Ver abajo |
| 5 | `ubigeo` | 0 | 1,917 | 6 dígitos, **ubigeo electoral** |
| 6 | `departamento` | 0 | 25 | |
| 7 | `provincia` | 9,981 | 196 | Nulo en filas regionales |
| 8 | `distrito` | 29,938 | 1,569 | Nulo en regional y provincial |
| 9 | `distrito_electoral` | **101,617** | 0 | **Columna íntegramente vacía. Descartar.** |
| 10 | `jurado_electoral` | 0 | 91 | JEE. Son 91, no 60 |
| 11 | `organizacion_id` | 0 | 74 | Es el `id_jne` |
| 12 | `organizacion` | 0 | **73** | Un nombre menos que ids: hay choque |
| 13 | `tipo_organizacion` | 0 | 3 | |
| 14 | `expediente_id` | 0 | 11,255 | |
| 15 | `cod_expediente` | 0 | 11,255 | Formato `ERM.2026013015` |
| 16 | `solicitud_lista_id` | 0 | 11,255 | **Llave natural de lista** |
| 17 | `estado_lista` | 0 | 10 | |
| 18 | `lista_cand_hombres` | 0 | 59 | Redundante, a nivel de lista |
| 19 | `lista_cand_mujeres` | 0 | 60 | Redundante, a nivel de lista |
| 20 | `candidato_id` | 0 | **101,617** | Llave primaria, única |
| 21 | `dni` | 0 | 101,599 | 18 repetidos, ver §1.6 |
| 22 | `candidato` | 0 | 101,582 | Nombre completo concatenado |
| 23 | `apellido_paterno` | 0 | 9,989 | |
| 24 | `apellido_materno` | 0 | 10,988 | |
| 25 | `nombres` | 0 | 61,659 | |
| 26 | `sexo` | 0 | 2 | `M` 55,292 / `F` 46,325 |
| 27 | `fecha_nacimiento` | 0 | 20,167 | `DD/MM/AAAA` |
| 28 | `edad` | 0 | 80 | |
| 29 | `cargo_id` | 0 | 8 | |
| 30 | `cargo` | 0 | 8 | |
| 31 | `posicion` | 0 | 41 | Entera, `0`–`40`. Ver §1.4 |
| 32 | `provincia_consejero` | 92,338 | 195 | **Nombre, no ubigeo.** Ver §1.5 |
| 33 | `ubigeo_postula` | 0 | 1,917 | **Idéntica a `ubigeo` en las 101,617 filas** |
| 34 | `estado_candidato` | 0 | 13 | |
| 35 | `hoja_vida_id` | 0 | 90,818 | `0` es centinela. Ver §2 |

Dos columnas sobran: `distrito_electoral` (vacía) y `ubigeo_postula` (duplicado
exacto de `ubigeo`). No se llevan a `processed/`.

### 1.1 Tipo de elección y cargo

`tipo_eleccion` tiene solo **tres** valores, pero `race_id` distingue **cuatro** tipos:
la elección `REGIONAL` contiene tanto la carrera de gobernador (`01`) como las de
consejero (`02`). **El `race_id` se deriva de `cargo`, no de `tipo_eleccion`.**

| cargo | cargo_id | n | tipo_eleccion | tipo de `race_id` |
|---|---|---|---|---|
| GOBERNADOR REGIONAL | 6 | 328 | REGIONAL | `01` |
| VICEGOBERNADOR REGIONAL | 7 | 326 | REGIONAL | `01` |
| CONSEJERO REGIONAL | 12 | 4,696 | REGIONAL | `02` |
| ACCESITARIO | 13 | 4,631 | REGIONAL | `02` |
| ALCALDE PROVINCIAL | 8 | 1,703 | MUNICIPAL PROVINCIAL | `03` |
| REGIDOR PROVINCIAL | 9 | 18,254 | MUNICIPAL PROVINCIAL | `03` |
| ALCALDE DISTRITAL | 10 | 9,208 | MUNICIPAL DISTRITAL | `04` |
| REGIDOR DISTRITAL | 11 | 62,471 | MUNICIPAL DISTRITAL | `04` |

**`ACCESITARIO` es un cargo explícito de la fuente.** No hay que deducirlo del orden,
como la spec contemplaba por si acaso. La tarea 4 de la fase 00 se resuelve con una
comparación de igualdad: `es_accesitario = (cargo_id == 13)`. Tasa de acierto: 100 %
por construcción. El accesitario aparece solo en listas regionales de consejo, nunca
en las municipales, que es lo que manda la regla.

### 1.2 Cobertura geográfica — cuadra exacto

| tipo_eleccion | ubigeos distintos | esperado (ARQUITECTURA) | |
|---|---|---|---|
| REGIONAL | 25 | 25 | ✅ |
| MUNICIPAL PROVINCIAL | 196 | 196 | ✅ |
| MUNICIPAL DISTRITAL | 1,696 | 1,696 | ✅ |

25 + 196 + 1,696 = 1,917 ubigeos distintos, que es exactamente la cardinalidad
observada de `ubigeo`. La forma del ubigeo es consistente con el nivel sin una sola
excepción: regional termina en `0000`, provincial en `00`, distrital en ningún cero
forzado. Los 25 ubigeos regionales son `010000`–`250000`, con **Callao = `240000`** y
**Lima = `140000`**, confirmando la regla 8 de `CLAUDE.md`.

Las 1,696 carreras distritales confirman que **los 196 distritos capital de provincia
no tienen elección distrital propia**: 1,892 distritos − 196 = 1,696.

Faltan las carreras de consejero para llegar a las 2,118 totales. Ver §1.5.

### 1.3 Listas

**11,255 listas.** `solicitud_lista_id`, `expediente_id` y `cod_expediente` son
biyectivos entre sí; cualquiera sirve de llave. Se adopta `solicitud_lista_id`.

Verificado: ninguna lista cruza ubigeos, organizaciones, tipos de elección,
expedientes ni estados. Una lista es un bloque homogéneo. `estado_lista` es un
atributo de la lista, no del candidato.

Listas por carrera: distrital 1–24 (media 5.4), provincial 3–27 (media 8.7), regional
7–20 (media 13.3). Tamaño de lista: 1 a 54 candidatos.

### 1.4 `posicion` — el 0 no es un error

Nunca es nula y siempre es un entero, pero **el ejecutivo municipal usa la posición 0**:

| cargo | rango | filas en posición 0 |
|---|---|---|
| ALCALDE DISTRITAL | 0–1 | 9,206 de 9,208 |
| ALCALDE PROVINCIAL | 0–1 | 1,702 de 1,703 |
| GOBERNADOR REGIONAL | 1 | 0 |
| VICEGOBERNADOR REGIONAL | 2 | 0 |
| REGIDOR DISTRITAL | 1–16 | 0 |
| REGIDOR PROVINCIAL | 1–40 | 0 |
| CONSEJERO REGIONAL / ACCESITARIO | 1–7 | 0 |

La convención es inconsistente entre niveles: el alcalde va en 0 y su cuerpo de
regidores arranca en 1, mientras que el gobernador va en 1 y el vicegobernador en 2.
**Tres alcaldes (2 distritales, 1 provincial) están en posición 1 en vez de 0**, y son
la excepción a revisar al normalizar. `posicion` no debe usarse como índice del cuerpo
proporcional sin filtrar antes por cargo.

Los regidores provinciales llegan a la posición 40, coherente con Lima Metropolitana.

### 1.5 Consejeros regionales — la brecha del Callao, y cómo se cierra

`provincia_consejero` viene como **nombre en texto**, no como ubigeo, y hay que
resolverlo. Buena noticia: **no hay colisión de nombre de provincia entre
departamentos** en todo el país, así que el par `(departamento, provincia_consejero)`
identifica unívocamente. El join es seguro.

Hay 195 valores distintos. Contra las 196 provincias del país, la única ausente es
**LIMA**, correcto: Lima Metropolitana no elige consejeros.

Pero la referencia `data/reference/consejeros_2026.csv` tiene **201 filas**, porque en
el Callao la circunscripción es el **distrito**, no la provincia. La fuente colapsa
los 216 candidatos de consejo del Callao bajo `provincia_consejero = CALLAO`, con
`ubigeo = 240000`, `provincia` y `distrito` nulos. 195 − 1 + 7 = 201: la brecha son
exactamente los 7 distritos del Callao.

**Resuelto con la hoja de vida.** El JSON de la HDV trae `strPostulaDistrito`, la
circunscripción real por la que postula el candidato. Para los 181 de 216 candidatos
de consejo del Callao que tienen HDV descargada, el reparto es:

| Distrito | candidatos con HDV | escaños (referencia) |
|---|---|---|
| CALLAO | 60 | 4 |
| VENTANILLA | 44 | 3 |
| BELLAVISTA | 16 | 1 |
| LA PERLA | 16 | 1 |
| MI PERU | 16 | 1 |
| CARMEN DE LA LEGUA-REYNOSO | 15 | 1 |
| LA PUNTA | 14 | 1 |

Los siete distritos aparecen y las proporciones siguen a los escaños. Para los 35 sin
HDV se segmenta dentro de su propia lista: ordenando por `candidato_id`, la secuencia
de `posicion` reinicia en 1 en cada cambio de distrito, produciendo bloques
`[1,2,3,4][1,2,3][1][1][1][1][1]` idénticos en las 9 listas del Callao y calzando con
`[4,3,1,1,1,1,1]` de la referencia.

> **Advertencia registrada.** La segmentación por posiciones, **sola, se equivoca**.
> Los cinco distritos de un escaño son indistinguibles por tamaño de bloque, y el
> orden real observado en la HDV —Callao, Ventanilla, Carmen de la Legua, Bellavista,
> La Punta, Mi Perú, La Perla— **no** es el orden en que están escritos en
> `consejeros_2026.csv`. Etiquetar por posición contra el orden del archivo de
> referencia habría asignado mal cuatro de los siete distritos. La HDV manda; la
> segmentación solo hereda el orden que la HDV ya fijó **en esa misma lista**.

**48 filas de consejo tienen `provincia_consejero` nula**, todas de cargo
`ACCESITARIO`, repartidas en 15 departamentos. Quedan pendientes de resolver por HDV
con el mismo método. Ninguna es `CONSEJERO REGIONAL` titular.

Además, 4 nombres de provincia no cruzan contra `consejeros_2026.csv` porque la
referencia está escrita sin eñes ni tildes, como su propio README advierte:
`FERREÑAFE`, `CAÑETE`, `DATEM DEL MARAÑON`, `MARAÑON`. Se resuelve normalizando a
ASCII en ambos lados antes del join.

### 1.6 Estados y anomalías

`estado_lista` (10 valores) y `estado_candidato` (13) son **independientes**: una lista
`ADMITIDO` puede contener candidatos `IMPROCEDENTE` (2,635 casos), que es el mecanismo
normal de exclusión individual. Nunca se debe inferir uno del otro.

| estado_lista | n | | estado_candidato | n |
|---|---|---|---|---|
| ADMITIDO | 53,228 | | ADMITIDO | 50,637 |
| INSCRITO | 28,702 | | INSCRITO | 27,330 |
| PERIODO DE TACHA | 12,717 | | PUBLICADO PARA TACHAS | 11,891 |
| IMPROCEDENTE | 5,862 | | IMPROCEDENTE | 10,234 |
| TACHA EN TRAMITE | 735 | | TACHA EN TRAMITE | 515 |
| APELACIÓN | 125 | | EXCLUSION | 279 |
| INADMISIBLE | 110 | | RENUNCIA | 250 |
| RECIBIDO | 68 | | APELACIÓN | 190 |
| RETIRO | 37 | | INADMISIBLE | 151 |
| RENUNCIA | 33 | | RECIBIDO | 79 |
| | | | RETIRO | 48 |
| | | | TACHADO | 12 |
| | | | FALLECIDO | 1 |

`APELACIÓN` lleva tilde y `EXCLUSION` no: el vocabulario del JNE es inconsistente en
acentuación. No normalizar a ciegas; conservar el literal y mapear explícito.

Sólo 28,702 de 101,617 candidatos están en listas `INSCRITO`, o sea **el registro está
lejos de ser definitivo**. Esto refuerza la urgencia del snapshot diario.

**Ejecutivo regional incompleto — 4 listas.** Deberían ser 328 gobernadores y 328
vicegobernadores; hay 328 y 326. Cuatro listas regionales no tienen el par (1,1), y
**las cuatro están `IMPROCEDENTE`**, así que no son un defecto de la fuente sino
candidaturas caídas: Tacna/Frente de la Esperanza 2021 (sin vice), y tres de Primero
la Gente en Cajamarca, Ica y Pasco.

**36 filas con DNI repetido = 18 personas en dos listas.** No son duplicados de fila:
son la misma persona postulando a dos cargos distintos, casi siempre con una de las
dos candidaturas ya `IMPROCEDENTE` (p. ej. Mario Genaro Copa Conde, consejero por
Tacna con Renovación Popular en improcedente y alcalde provincial de Candarave con
Unidos por Tacna en admitido). `candidato_id` sigue siendo único. **No deduplicar por
DNI.**

**97 pares (lista, provincia) tienen distinto número de consejeros que de
accesitarios**, contra la regla de que van en igual número. Hay que revisarlos uno por
uno contra el estado del candidato antes de la proclamación; casi todos parecen
exclusiones individuales que rompieron el par.

### 1.7 Organizaciones — el choque de denominación, confirmado

74 `organizacion_id`, 73 nombres distintos. El choque es **exactamente el que
`ARQUITECTURA.md` anticipa**:

| id_jne | Denominación | tipo_organizacion | candidatos |
|---|---|---|---|
| 14 | PARTIDO DEMOCRATICO SOMOS PERU | PARTIDOS POLITICOS | 9,174 |
| 3045 | PARTIDO DEMOCRATICO SOMOS PERU | ALIANZAS ELECTORALES | 310 |

Se desambiguan por `tipo_organizacion`, que la fuente sí trae. El emparejamiento por
nombre contra el acta del sorteo seguirá necesitando el puente por posición.

Composición: **41 partidos políticos, 23 movimientos regionales, 10 alianzas
electorales.** Los 23 movimientos coinciden con lo que `specs/03-sorteo-cedula.md`
anticipa, así que **varias ODPE no sortearán** y hay que saber cuáles antes del 18.

### 1.8 `organizaciones_erm2026.csv`

74 filas × 15 columnas, una por organización. Cruza perfecto con el CSV de candidatos:
0 organizaciones en una fuente y no en la otra, en ambos sentidos.

`organizacion_id, organizacion, tipo_organizacion, grupo_id, grupo, grupo_n_orgs,
es_ancla, listas, candidatos, reg, prov, dist, n_departamentos, departamentos,
integrantes`

Los campos `listas`, `candidatos`, `reg`, `prov`, `dist`, `n_departamentos` son
agregados derivables del CSV de candidatos: **no se importan, se recalculan**.

Lo que sí es insumo nuevo y no está en ninguna otra fuente: **`integrantes`**, que
lista los partidos que componen cada alianza, separados por ` | ` (p. ej. Alianza
Electoral Venceremos = Nuevo Perú por el Buen Vivir, UP, Popular Voces del Pueblo,
Adelante Pueblo Unido, RUNA). Ese campo es directamente el insumo de la fase 05 para
decidir el `bloque` de cada alianza. Falta, y hay que añadirlos: `siglas`, `ambito`,
`ubigeo_ambito`, `logo_path`.

---

## 2. `hdv_erm2026.sqlite`

369 MB, 4 tablas. **Los blobs están comprimidos con `zlib` puro, no con gzip**
(cabecera `78 9c`); `gzip.decompress` falla, hay que usar `zlib.decompress`.

| Tabla | Filas | Columnas |
|---|---|---|
| `meta` | 96,496 | `hoja_vida_id, org_id, proceso_id, dni, sig, ok, n_penal, n_obliga, edu_max, foto, fetched_at` |
| `raw` | 96,496 | `hoja_vida_id, gz (BLOB zlib), fetched_at` |
| `sentencia_penal` | 2,683 | `hoja_vida_id, item, expediente, fecha, organo, delito, fallo, modalidad, cumple` |
| `sentencia_obliga` | 5,186 | `hoja_vida_id, item, materia, expediente, organo, fallo` |

Las 96,496 filas de `meta` tienen `ok = 1` sin excepción, y 96,473 tienen foto.

### Cobertura

`hoja_vida_id = 0` es un **centinela de "sin hoja de vida"**, no un id: lo llevan
**10,800 candidatos**. Los otros 90,817 ids son únicos y **los 90,817 están presentes
en `meta` y en `raw`: cobertura del 100 %, cero descargas faltantes.** `meta` es
superconjunto (96,496) porque conserva hojas de candidatos que ya salieron del
registro — coherente con la memoria de que el `--update` pierde HDV al diffear listas.

Los 10,800 sin HDV son el 10.6 % del padrón y **no** son un fallo del scraper: no
existe hoja publicada para ellos. Se marcan como faltantes, nunca se rellenan.

### El JSON de la hoja de vida

Estructura `{"data": {"oDatosPersonales": {...}, ...}}`, ~15 KB por candidato.
`oDatosPersonales` trae, entre otros, cuatro bloques de ubigeo con nombre y código:
nacimiento (`strNaci*`), domicilio (`strDomi*`), inmueble (`strInmueble*`) y
**postulación (`strPostula*`)**. Hay además listas de cargos de elección y partidarios
(`lCargoElecPostula`, `lCargoElecHistorico`, `lCargoPartidario`, …).

`strPostulaDepartamento / strPostulaProvincia / strPostulaDistrito` son la pieza que
cierra la brecha del Callao (§1.5). Nótese que los campos hermanos
`strPostulaUbi*` vienen en **`null`** en las filas inspeccionadas: **el código de
ubigeo no está poblado, solo el nombre.** Hay que resolver nombre → ubigeo igual, con
el mismo normalizador ASCII.

---

## 3. Consecuencias para la normalización

Lo que este inventario deja decidido para el paso 2 de la fase 00:

1. `race_id` se deriva de **`cargo`**, no de `tipo_eleccion`, porque `REGIONAL` mezcla
   los tipos `01` y `02`.
2. `es_accesitario = (cargo_id == 13)`. Directo, sin heurística.
3. `lista_id = solicitud_lista_id`; `cand_id = candidato_id`; `id_jne = organizacion_id`.
4. `ubigeo_provincia_consejero` se resuelve por `(departamento, provincia_consejero)`
   normalizado a ASCII, **salvo en el Callao**, donde se resuelve por
   `strPostulaDistrito` de la HDV.
5. Se descartan `distrito_electoral` (vacía), `ubigeo_postula` (duplicada) y los
   agregados de `organizaciones_erm2026.csv`.
6. No hay `fecha_estado` en la fuente. **El campo que `ARQUITECTURA.md` pide en
   `listas` no existe hoy**; solo podrá poblarse a partir del primer diff entre
   snapshots diarios, y antes de eso queda nulo. Una razón más para arrancar el
   snapshot ya.

## 4. Pendientes que salen de este inventario

- [ ] Resolver por HDV los 48 accesitarios con `provincia_consejero` nula.
- [ ] Revisar los 3 alcaldes en posición 1 en vez de 0.
- [ ] Revisar los 97 pares (lista, provincia) con consejeros ≠ accesitarios.
- [ ] Conseguir `siglas`, `ambito`, `ubigeo_ambito` y logos de las 74 organizaciones
      (fase 05).
- [ ] Levantar el stack declarado: **no hay `uv` ni `duckdb` instalados** en la máquina
      del operador. Este inventario corrió con `pandas` 2.2.2, `pyarrow` 23.0.1 y
      `sqlite3` de stdlib sobre Python 3.12.4.
