# Arquitectura de datos

Define identificadores, tablas, formatos y flujos. Las specs por fase implementan
lo que aquí se declara.

## 1. Identificadores

### `race_id` — identifica una contienda

```
race_id = {tipo}-{ubigeo_circunscripcion}
```

| tipo | Cargo | Circunscripción | Ejemplo |
|---|---|---|---|
| `01` | Gobernador y vicegobernador | departamento | `01-140000` |
| `02` | Consejeros regionales | provincia; **distrito en Callao** | `02-160200`, `02-240103` |
| `03` | Alcalde y regidores provinciales | provincia | `03-140100` |
| `04` | Alcalde y regidores distritales | distrito | `04-140140` |

### `result_key` — identifica una celda de resultado

```
result_key = {tipo}-{nivel}-{codigo}      nivel: 01 = distrito, 02 = mesa
```

`03-01-140140` son los resultados de la carrera provincial de Lima **vistos desde**
San Borja. No es una carrera, es una desagregación. `04-02-055327` son los
resultados de la alcaldía distrital en la mesa 055327.

No hay colisión entre ubigeos y códigos de mesa: los ubigeos electorales no
empiezan en 9 y las mesas especiales sí.

**En almacenamiento, `tipo`, `nivel` y `codigo` van como columnas separadas.** El
string compuesto se usa solo para nombres de archivo y rutas de publicación.
Parsear strings en la ruta caliente es una fuente de bugs.

## 2. Registros estáticos

Se congelan antes del 4 de octubre. Formato: **CSV versionado en git** (chicos,
revisables en diff) más espejo Parquet para el pipeline.

### `distritos.csv` — 1,896 filas. La tabla que elimina todas las excepciones

| Campo | Nota |
|---|---|
| `ubigeo_distrito` | 6 dígitos, ubigeo electoral |
| `ubigeo_provincia`, `ubigeo_departamento` | |
| `nombre_distrito`, `nombre_provincia`, `nombre_departamento` | |
| `race_gobernador` | `race_id` o **null** |
| `race_consejero` | `race_id` o **null** |
| `race_provincial` | `race_id` o **null** |
| `race_distrital` | `race_id` o **null** |
| `es_capital_provincia` | bool |
| `electores_habiles` | |
| `odpe` | una de las 125 |

Las excepciones se declaran como datos, no como lógica:

- Distritos de **Lima provincia** (`1401xx`): `race_gobernador` y `race_consejero`
  en null.
- Distritos del **Callao**: `race_consejero = 02-{ubigeo_distrito}`, no
  `02-{ubigeo_provincia}`.
- **Distritos capital de provincia** (196): `race_distrital` en null.
- La región **Lima provincias** tiene ODPE propia en Huaura y es circunscripción
  regional separada de Lima Metropolitana.

Ningún script debe derivar estas reglas. Se leen de la tabla.

### `carreras.csv` — ~2,118 filas

`race_id, tipo, id_tipo_jne, ubigeo, nivel_circunscripcion, cargo_ejecutivo,
cargo_proporcional, n_escanos, fuente_n_escanos, umbral_primera_vuelta,
tiene_segunda_vuelta, electores_habiles, n_mesas, jee, odpe, estado`

`estado`: `normal`, `sin_eleccion`, `suspendida`.

Cuadre obligatorio: 25 + 201 + 196 + 1,696 = 2,118 carreras, y la suma de
`n_escanos` más los ejecutivos debe dar 13,148 autoridades. Ver
`shared/REGLAS-ELECTORALES.md`.

### `mesas.csv` — 89,935 filas

`mesa, ubigeo_distrito, local_id, nombre_local, electores_habiles, ambito`

Rangos verificados para ERM 2026: `000001`–`084992` (84,992) y `900001`–`904943`
(4,943). Suman exactamente 89,935, la cifra oficial, así que **ambos rangos son
densos y no hay huecos internos**. El enumerador itera rangos, no un catálogo.

La pertenencia de una mesa a una carrera **no se almacena**: se deriva por join
contra `distritos.csv`. Una mesa participa en las carreras que su distrito declara
no nulas.

### `organizaciones.csv`

`id_jne, nombre_oficial, siglas, tipo_org, ambito, ubigeo_ambito, bloque, logo_path`

`tipo_org`: partido, movimiento regional, alianza. `bloque`: `partidos` o
`movimientos`; para alianzas se determina por alcance y **debe verificarse contra
el acta del sorteo**, no inferirse del nombre.

### `listas.csv` y `candidatos.csv`

`listas`: `lista_id, race_id, id_jne, expediente, estado_lista, fecha_estado`

`candidatos`: `cand_id, lista_id, posicion, cargo, es_accesitario, nombres,
apellidos, dni, sexo, ubigeo_provincia_consejero, hoja_vida_url, foto_url,
estado_candidato`

`posicion` y `es_accesitario` son críticos: listas cerradas, y los accesitarios no
se proclaman.

## 3. El puente de organizaciones políticas

Es la pieza de mayor riesgo.

### La llave canónica es `codigo_onpe`, no la posición

**Todo el pipeline se indexa por `codigo_onpe` (`adAgrupacionPolitica`).** El flujo
distrital devuelve `codigoAgrupacionPolitica` y **no** devuelve la posición de
cédula, así que un pipeline construido sobre `adPosicion` dejaría ese flujo sin
llave.

`adPosicion` se usa **una sola vez**, al inicio de la jornada, para resolver
`codigo_onpe → id_jne`. Después no reaparece salvo para ordenar en pantalla.

### Dos puentes encadenados

```
id_jne  →  posicion_cedula        (lo construimos tras el sorteo del 18/08)
posicion_cedula  →  codigo_onpe   (lo entrega la ONPE en cada acta)
```

Como `adAgrupacionPolitica` es **nacional** (verificado en ERM 2022: Fuerza Popular
fue 6 en Lima y en Arequipa), basta resolverlo en una carrera por organización y
vale para todo el país.

### El emparejamiento por nombre no basta

En ERM 2026 hay al menos un choque exacto de denominación:

| id_jne | Denominación | Tipo |
|---|---|---|
| 14 | Partido Democrático Somos Perú | Partido |
| 3045 | Partido Democrático Somos Perú | Alianza |

El nombre no puede desambiguarlas. **El puente por posición es necesario, no un
acelerador.** `adDescripcion` sirve como verificación cruzada.

### Tablas

`cedula.csv` — versionada con fecha, **nunca sobrescrita** (ver art. 6 del sorteo):
`version_fecha, bloque, ubigeo_sorteo, posicion, id_jne, correlativo_alfabetico`

`ubigeo_sorteo`: `000000` para el sorteo nacional; el ubigeo del departamento para
cada sorteo regional. Huaura corresponde a la región Lima provincias.

`crosswalk.csv`:
`codigo_onpe, id_jne, posicion_cedula, correlativo_alfabetico, bloque,
ubigeo_sorteo, nombre_onpe, nombre_jne, metodo, confianza`

`metodo`: `posicion`, `nombre` o `ambos`. Toda fila con `metodo != ambos` va a
revisión manual antes de publicar.

### Degradación

Mientras el puente no cierre, los resultados se muestran con el nombre de
`adDescripcion`, sin foto ni ficha. Peor que lo ideal, mucho mejor que una pantalla
vacía a las 17:30.

## 4. Resultados

### Formato largo, no ancho

Un archivo por nivel, en **formato largo**, en Parquet.

```
resultados_distrito:  snapshot_ts, tipo, ubigeo_distrito, codigo_onpe, votos
resultados_mesa:      tipo, mesa, codigo_onpe, votos, version
```

Razones para descartar el formato ancho (una columna por organización):

1. El conjunto de organizaciones cambia por carrera; una tabla nacional tendría
   ~400 columnas casi todas vacías.
2. **No se conocen los nombres de columna hasta que el crosswalk resuelve el
   domingo.** Un esquema ancho no se puede pre-generar; uno largo sí.
3. Añadir una organización tardía obliga a reescribir el esquema.

El pivote a ancho se hace **al publicar**.

### Un solo archivo de mesa, no cuatro

El endpoint devuelve las cuatro elecciones en una respuesta. Partirlo obliga a
cuatro escrituras por request y convierte el análisis cruzado (voto diferenciado
entre provincial y distrital) en un join. El rendimiento se resuelve
**particionando el Parquet** por `ubigeo_departamento` y `tipo`.

### Metadatos por unidad, en tabla aparte

```
computo_distrito: snapshot_ts, tipo, ubigeo_distrito, actas_contabilizadas,
                  actas_procesadas, actas_por_procesar, actas_observadas,
                  electores, emitidos, validos, blancos, nulos, impugnados
computo_mesa:     tipo, mesa, estado_acta, ever_observada, electores, emitidos,
                  ts_digitalizacion, ts_digitacion, ts_contabilizacion
```

### Snapshots: distrito sí, mesa no

**Distrito**: append-only, un snapshot por ciclo. ~2,100 unidades × ~15
organizaciones = ~30 mil filas por ciclo. Irrelevante en tamaño y permite
reconstruir la noche.

**Mesa**: escritura única. Un acta contabilizada es final salvo resolución del
JEE. Se guarda `version` para ese caso raro; la última gana. La información
temporal ya está en `ts_contabilizacion`.

### Pre-generación

Lo que se pre-genera **no es la matriz de resultados vacía**, son los registros:
`mesas.csv`, `distritos.csv`, `carreras.csv`. Con eso el enumerador ya sabe qué
pedir. Las filas de resultado nacen cuando llega el dato.

## 5. Mapas

### Geometrías

Un topojson nacional por nivel (departamento, provincia, distrito), simplificado,
**pre-cortado por provincia**: 196 archivos con los distritos de esa provincia.
Mismo corte que los resultados publicados. No se genera un archivo por carrera.

### Mapas por tipo de carrera

| Mapa | N | Niveles | Fuente |
|---|---|---|---|
| Gobernador | 25 | departamento, provincia, distrito | flujo distrital |
| Consejero regional | 25 | circunscripción (provincia; distrito en Callao) | flujo distrital + reparto |
| Alcalde provincial | 196 | provincia, distrito | flujo distrital |
| Alcalde distrital | 1,696 | distrito | flujo distrital |

El mapa de consejeros muestra **la composición del consejo**, no una participación
de voto: cada circunscripción se representa por sus escaños. Antes de que exista
proyección muestra el **reparto aplicado al corte actual** (allocator sobre los
votos contabilizados, sin simulación), marcado explícitamente como reparto al
corte. Es determinista y responde mejor "quién estaría ganando ahora" que mostrar
solo el más votado, porque en una circunscripción de cuatro escaños el más votado
no describe el resultado.

## 6. Proyección y autoridades

Se construyen desde el flujo de mesa.

### `forecast`

```
race_id, snapshot_ts, id_jne, p_primero, p_gana_1v, p_pasa_2v,
escanos_p10, escanos_p50, escanos_p90, escanos_garantizados, prob_por_escano
```

Más, a nivel de carrera: `p_segunda_vuelta`, `pct_actas`,
`pct_electorado_locales_frios`, `capa_usada`.

`escanos_garantizados` es el mayor k tal que la lista obtiene al menos k escaños en
el 100% de las simulaciones. Es el número que activa la proyección de autoridades
proporcionales.

**Sobre la suma de probabilidades.** Para alcaldes, `p_primero` suma 1 entre
candidatos. Para gobernador no: exactamente uno de dos mundos ocurre, alguien gana
en primera o dos pasan a segunda. `p_gana_1v + p_pasa_2v` sumado sobre candidatos
da `1 + p_segunda_vuelta`. Son tres números distintos; no fuerces una normalización
que sería falsa.

### `autoridades`

```
race_id, cargo, orden, id_jne, cand_id, estado, ts_call, pct_actas_al_call,
metodo, revocada_ts
```

`estado`: `por_definir` | `proyectado` | `electo` | `proclamado`.

**La tabla se pre-puebla completa antes de la jornada**, con una fila por cada
cargo en disputa: el ejecutivo más los `n_escanos` asientos proporcionales, todos
en `por_definir` con `id_jne` y `cand_id` nulos. Así la tabla está completa desde el
minuto cero, la página muestra la alcaldía y todos los escaños como "por definir"
sin que el frontend fabrique filas de relleno, y el avance de la noche es
literalmente el llenado de esa tabla.

Derivación mecánica gracias a las listas cerradas: si una lista tiene
`escanos_garantizados = 2`, los candidatos **titulares** en posición 1 y 2 de esa
lista para ese cargo pasan a `proyectado`.

Para el ejecutivo, `estado = electo` requiere imposibilidad matemática o
proclamación del JEE, no umbral de modelo.

**Append-only con `revocada_ts`.** Una llamada retirada deja rastro y dispara
alarma. Nunca se borra en silencio.

## 7. Resumen nacional

Un solo archivo, anidado por departamento para que el zoom funcione sin peticiones
adicionales.

```
por_organizacion: id_jne, nivel, proyectadas, electas, en_segunda_vuelta, en_disputa
por_ubigeo:       ubigeo, nivel, {mismo desglose}
```

Es una agregación de `autoridades` y `forecast` calculada al publicar, no una tabla
que se mantenga aparte.

Para consejeros, la agregación es **a nivel de región**: escaños por organización
en el consejo completo, sumando las asignaciones provinciales.

## 8. Flujos

### Flujo A — distrital

```
scrape agregado -> resultados_distrito + computo_distrito -> mapas -> publicar
```

Cada 60 a 90 segundos, ~2,100 circunscripciones. Clasifica cada carrera en
`resuelta` / `competitiva` / `dormida`. **Debe poder publicar sin el flujo B.**

### Flujo B — mesa

```
scrape mesa -> resultados_mesa + computo_mesa -> forecast -> autoridades
            -> resumen nacional -> publicar
```

Cola incremental. Barrido completo inicial, después solo actas cuyo estado no es
`C`. Una petición trae las cuatro carreras de esa mesa.

### Publicación

Atómica: un manifiesto con la versión del ciclo se escribe al final. Un ciclo a
medias nunca queda visible.

Corte por provincia: 196 archivos con todos sus distritos, más 25 regionales y un
nacional. No 2,100 archivos por ciclo.

```
/api/{proceso}/resumen.json
/api/{proceso}/regiones/{ubigeo_dep}.json
/api/{proceso}/provincias/{ubigeo_prov}.json
/api/{proceso}/carrera/{race_id}.json
/api/{proceso}/estatico/carreras.json
/api/{proceso}/estatico/candidatos/{race_id}.json
```

**Separar lo estático de lo vivo.** Nombres, fotos y logos no cambian durante la
jornada y no deben viajar en cada actualización. Todo objeto lleva su propio
timestamp. Nulos explícitos: si no hay proyección, el campo es `null` y el frontend
muestra "sin proyección", nunca un cero.

## 9. Presupuesto de ciclo

| Etapa | Objetivo |
|---|---|
| Scrape distrital (flujo A) | 60–90 s |
| Parseo y persistencia | 10 s |
| Proyecciones (~2,100 carreras) | 20–30 s |
| Render y publicación atómica | 20 s |

El cuello de botella es el scrape, no el cómputo.
