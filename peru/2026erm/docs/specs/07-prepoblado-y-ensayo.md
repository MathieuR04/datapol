# Fase 07 — Pre-poblado y ensayo general

## Objetivo

Dejar todo lo estático congelado y ensayar la jornada completa. Es la última fase
del bloque 2026 y solo se cierra cuando el sitio de 2022 ya funciona y fue portado.

## Pre-poblado

1. **`autoridades.parquet` completa**, una fila por cargo en disputa: el ejecutivo
   más los `n_escanos` asientos proporcionales de cada carrera, todos en
   `estado = por_definir`, con `id_jne` y `cand_id` nulos.
   Total: 13,148 filas. Ver `shared/ARQUITECTURA.md` sección 6.
2. **Archivos estáticos de publicación**: `carreras.json` y
   `estatico/candidatos/{race_id}.json` con nombres, fotos, logos y fichas. No
   cambian durante la jornada y no deben viajar en cada actualización.
3. **Geometrías**: topojson por nivel, pre-cortado por provincia.
4. **Archivos vivos en cero**: resumen, regiones y provincias con estructura
   completa y valores nulos, para que la página cargue algo coherente a las 17:00
   antes del primer resultado.

## Ensayo general

Simula la jornada completa con el pipeline real:

1. Arranca con todo en cero.
2. Alimenta el flujo A y el flujo B desde los datos archivados de ERM 2022,
   reproducidos en el tiempo (ver `2022/specs/05-replay-calibracion.md`).
3. Verifica que el ciclo completo cabe en tres minutos.
4. Verifica que la publicación es atómica y que un ciclo interrumpido no deja el
   sitio en estado inconsistente.
5. Prueba de carga contra el objetivo de 20,000 usuarios concurrentes.

## Plan de degradación (documentar y probar)

- **Sin crosswalk**: mostrar resultados con `adDescripcion`, sin foto ni ficha.
- **Sin flujo B**: mostrar resultados y mapas, con la sección de proyección en
  "sin proyección" y autoridades en `por_definir`.
- **Sin flujo A**: no hay página. Es el único componente sin degradación, así que
  es el que necesita más margen de concurrencia y reintentos.
- **ONPE caída o bloqueando**: mostrar el último ciclo válido con su timestamp
  visible, no una pantalla vacía ni datos sin fecha.

## Criterios de aceptación

- `autoridades.parquet` tiene 13,148 filas y cuadra con `carreras.csv`.
- El ensayo general corre de punta a punta sin intervención manual.
- Cada modo de degradación fue probado forzando el fallo, no solo documentado.
- `docs/ensayo-general.md` reporta tiempos por etapa y resultados de la prueba de
  carga.
