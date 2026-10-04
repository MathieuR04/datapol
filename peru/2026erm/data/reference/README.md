# Tablas de referencia ERM 2026

Versionadas en git. Son insumos verificados, no derivados del pipeline.

## `consejeros_2026.csv`

Transcripción de la **Resolución N.º 0001-2026-JNE** (2 de enero de 2026), que
establece el número de consejeros regionales por circunscripción.

Validado: **201 filas, 364 consejeros, 25 departamentos.**

Columnas: `departamento, provincia, consejeros_directos, consejeros_adicionales,
consejeros_total`.

Notas:

- Las siete filas del Callao son **distritos**, no provincias. La LER toma como
  referencia los distritos del Callao.
- Lima Metropolitana no aparece: no elige consejeros.
- Las nueve filas de LIMA son las provincias de la región Lima provincias.
- Nombres sin tildes ni eñes para evitar problemas de codificación. Hay que mapear a
  ubigeo electoral por normalización de nombre; verificar caso por caso los nombres
  compuestos.

## Pendiente: `regidores_2026.csv`

De la **Resolución N.º 0847-2025-JNE** (31 de diciembre de 2025). El PDF lo tiene el
operador. Artículo 1 lista solo los concejos con población mayor a 25,000; el
artículo 2 cierra: **todo concejo no listado tiene 5 regidores**.

Validación: `Σ n_regidores = 10,842`. Ver `2026/specs/02-escanos.md`.
