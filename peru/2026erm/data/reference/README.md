# Tablas de referencia ERM 2026

Versionadas en git. Son insumos verificados, no derivados del pipeline.

## `id_eleccion.csv`

Mapa ERM 2026 de `idEleccion` a tipo, confirmado con las rutas y filtros que
solicita la página oficial: 1 gobernador, 2 consejero regional, 3 alcalde
provincial y 4 alcalde distrital.

## `crosswalk_organizaciones_2026.csv`

Cruza el `codigoAgrupacionPolitica` de ONPE (`codigo_onpe`) con el
`idOrganizacionPolitica` del JNE (`id_jne`). Incluye 72 códigos del primer
corte completo de participantes: 71 conciliados por nombre normalizado con el
catálogo JNE ERM 2026 y uno conservado de la verificación previa de Amazonas.
Queda pendiente el código ONPE `161` (Partido Democrático Somos Perú). Es un
mapa incremental: `04_publica_resultados.py` sigue cruzando por nombre cuando
falta un código; se puede completar cuando aparezcan nuevos participantes.

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
