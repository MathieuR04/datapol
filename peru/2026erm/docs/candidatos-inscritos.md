# `candidatos_inscritos` — quién puede resultar electo

Corrida del **12 de agosto de 2026** sobre el registro del JNE del 11 de agosto.

Este archivo responde una sola pregunta: **quién, hoy, puede resultar electo el 4 de
octubre.** No es el padrón de candidaturas —eso es el registro crudo— sino el
subconjunto inscrito, con las dos reglas que el registro no expresa por sí solo ya
aplicadas.

**Crece con los días.** Hoy cubre 1,026 de las ~2,118 carreras porque el JNE todavía
está inscribiendo listas. Volver a correrlo es la forma de actualizarlo; no hay
snapshot ni acumulación, el archivo se reconstruye entero desde la fuente del día.

```
uv run python scripts/build_candidatos_inscritos.py
```

Salida: `data/processed/candidatos_inscritos.{parquet,csv}`.

## Corte de hoy

| | |
|---|---|
| Candidatos inscritos en listas inscritas | 27,330 |
| − accesitarios descartados (regla 2) | −451 |
| + promociones por vacancia (regla 1) | +57 |
| **Filas de salida** | **26,936** |
| Listas | 3,362 |
| Carreras cubiertas | 1,026 de ~2,118 |
| Filas sin `race_id` | 9 |

Por tipo de carrera: 828 distritales (`04`), 101 provinciales (`03`), 87 de consejo
regional (`02`), 10 de gobernador (`01`).

Los 27,330 inscritos **tienen los 27,330 hoja de vida descargada**. La cobertura de
HDV en el universo inscrito es total, como estaba previsto.

## Regla 1 — el alcalde caído y la doble candidatura

Cuando el candidato a alcalde renuncia, es excluido, tachado o declarado
improcedente, el primer regidor inscrito de la lista **suma** la candidatura a la
alcaldía **sin perder la suya**. Puede resultar electo en ambas o solo como regidor,
así que la persona ocupa **dos filas**, con `cand_id` distinto.

El registro del JNE **no expresa esto**: se verificó que no hay un solo par
(lista, DNI) con más de una fila en las 101,617. La derivación es nuestra.

- 58 listas inscritas tienen al alcalde caído en firme.
- **57 promociones** resueltas; 1 quedó sin resolver (ver abajo).
- En 54 casos el regidor 1 estaba inscrito y bastó un salto.
- En 3 casos el regidor 1 también había caído y hubo que bajar al siguiente.

Las filas derivadas se distinguen por `origen_candidatura = promocion_por_vacancia`,
llevan `reemplaza_cand_id` con el `candidato_id` del alcalde caído, y su `cand_id`
es el del regidor con sufijo `-ALC` para no colisionar con su fila de regidor.

> **El caso que muestra que esto importa.** En Lima Metropolitana (lista 41525,
> Renovación Popular) el candidato a alcalde Luis Isael Rubio Idrogo **renunció**, y
> el regidor 1 de esa lista es **Rafael López Aliaga**. Sin esta regla, la carrera
> más visible del país aparecería sin candidato por esa organización.

### Qué cuenta como caída

Se promueve solo ante caída **firme**: `EXCLUSION`, `RENUNCIA`, `RETIRO`, `TACHADO`,
`IMPROCEDENTE`, `INADMISIBLE`.

**No** se promueve ante estados aún en trámite: `APELACIÓN`, `TACHA EN TRAMITE`,
`PUBLICADO PARA TACHAS`, `ADMITIDO`, `RECIBIDO`. Un alcalde en apelación no ha sido
removido, y darlo por caído fabricaría una candidatura que no existe. Hoy hay **18
alcaldes en ese limbo** que no generan promoción; si alguno cae en firme, la
siguiente corrida la genera sola.

El criterio simétrico aplica al reemplazo: si el regidor 1 no está inscrito **pero
tampoco ha caído**, no se le puede pasar por encima para promover al regidor 2.
Ese caso se reporta sin resolver en vez de decidir por él.

## Regla 2 — el accesitario solo cuenta si el titular no está

El accesitario a consejero regional se descarta mientras su titular esté inscrito:
solo el titular puede resultar electo. Se conserva únicamente cuando el titular no
está inscrito, que es cuando pasa a ser relevante.

- 463 accesitarios inscritos; **451 descartados**, 12 conservados.
- De los 12, 3 tienen titular caído (el caso legítimo) y 9 son filas sin
  `provincia_consejero`, que se conservan por precaución (ver abajo).

El emparejamiento titular↔accesitario es por `(lista, circunscripción, posición)`,
no por posición sola: dos provincias de la misma lista tienen ambas una posición 1.

## Circunscripciones

`race_id` se deriva de **`cargo`**, no de `tipo_eleccion`: `REGIONAL` contiene tanto
gobernador (`01`) como consejero (`02`). Ver `docs/fuentes-locales.md` §1.1.

Para consejeros la circunscripción es **la provincia que representa el candidato**,
resuelta por `(departamento, provincia_consejero)` plegado a ASCII —la referencia
está escrita sin eñes y el JNE no—. Verificado: 0 consejeros con `race_id` apuntando
al departamento.

**Callao.** La circunscripción es el distrito, y el registro colapsa los siete bajo
`provincia_consejero = CALLAO`. Se resuelve con `strPostulaDistrito` de la hoja de
vida, contra `data/reference/callao_circunscripciones_consejero.csv`.

Hoy **no hay ningún consejero del Callao inscrito**, así que esta rama no produce
filas todavía. Está implementada y probada porque las producirá.

> Advertencia registrada en `fuentes-locales.md` §1.5: la alternativa de segmentar la
> secuencia de posiciones **habría asignado mal cuatro de los siete distritos**, y
> con todos los totales cuadrando. La HDV es la única fuente válida aquí.

## Lo que quedó sin resolver

Nada se rellenó. Todo lo que no se pudo determinar está marcado y se reporta en cada
corrida.

**9 filas sin `race_id`** — accesitarios con `provincia_consejero` nula en el
registro, en Loreto (1), Ucayali (3), San Martín (4) y Ayacucho (1). Son parte de las
48 filas con ese defecto detectadas en el inventario.

Las 9 están plenamente inscritas (lista y candidato) y las 9 tienen hoja de vida,
pero **la HDV tampoco las resuelve**: su bloque `strPostula*` viene en cadena vacía,
no con el distrito. Es el mismo defecto en las dos fuentes a la vez, así que el
método que sí funciona para el Callao aquí no aplica.

No se infieren. Se podría segmentar la secuencia de posiciones dentro de la lista,
pero ese es exactamente el método que en el Callao asigna mal cuatro de siete
circunscripciones sin que nada lo delate. Quedan en nulo hasta que el JNE complete el
dato.

**1 promoción sin resolver** — lista 46702 (Ayacucho, Huanta, Canayre, Frente de la
Esperanza 2021): el alcalde está `IMPROCEDENTE` pero el regidor 1 está `ADMITIDO`,
ni inscrito ni caído. No se promovió a nadie. Se resolverá solo cuando el JNE mueva
a ese regidor a un estado definitivo.

**`240101` verificado.** El ubigeo del distrito Callao cercado no aparece en el
registro, porque al ser capital de provincia no tiene elección distrital propia.
Confirmado por el operador: **las capitales de provincia llevan `01` como sufijo de
distrito**, así que la capital de la provincia `240100` es `240101`. En la tabla de
referencia queda como `fuente=regla_capital_provincia, verificado=SI`.

## Tests

`tests/test_candidatos_inscritos.py`, 16 casos sobre fixtures sintéticas: derivación
de `race_id` en las cuatro variantes, cruce con eñes, nulos que quedan nulos, la
promoción ante los seis estados de caída, la conservación de la doble candidatura, la
cascada, el freno ante estados en trámite y el descarte de accesitarios sin confundir
provincias.

```
uv run python -m pytest tests/ -q
```
