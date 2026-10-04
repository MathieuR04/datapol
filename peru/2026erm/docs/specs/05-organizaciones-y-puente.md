# Fase 05 — Organizaciones políticas y puente de cédula

## Objetivo

Cerrar la primera mitad del puente (`id_jne → posicion_cedula`) y dejar listo el
builder que cierra la segunda mitad (`posicion_cedula → codigo_onpe`) el domingo.

Lee `shared/ARQUITECTURA.md` sección 3 antes de empezar.

## Universo ERM 2026

74 organizaciones al cierre de inscripción: **41 partidos, 10 alianzas, 23
movimientos regionales**. Los movimientos están concentrados (Arequipa 4;
Cajamarca, Huánuco, Amazonas y Tacna 2 cada una), así que varias ODPE no realizan
sorteo de movimientos.

## Tareas

1. **`organizaciones.csv`** desde la fase 00, más el campo `bloque`
   (`partidos` / `movimientos`). Para alianzas el bloque depende del **alcance** y
   **debe verificarse contra el acta del sorteo**, no inferirse del nombre.
2. **`cedula.csv`** viene de la fase 03.
3. **Builder del crosswalk.** Script que, dado un lote de respuestas de acta de la
   API en vivo, produce `crosswalk.csv`. Dos rutas independientes:
   - **Por posición**: `adPosicion` + bloque + `ubigeo_sorteo` → `id_jne` vía
     `cedula.csv`. Ruta principal.
   - **Por nombre**: `adDescripcion` normalizado → `nombre_oficial`. Verificación
     cruzada.
   Emite `metodo` = `posicion` / `nombre` / `ambos`. **Toda discrepancia entre las
   dos rutas es una alarma**, no un empate a resolver en silencio.
4. **Detector de corrimientos.** Si el número de organizaciones de un bloque
   difiere entre `cedula.csv` y lo que reporta la ONPE, todas las posiciones bajo
   la exclusión están desplazadas (art. 6). El builder debe detectarlo y **negarse
   a producir un crosswalk** en vez de producir uno mal.
5. **Ensayo cronometrado.** El builder debe correr y cerrar en **menos de diez
   minutos** desde que la ONPE publica. Ensáyalo contra los datos archivados de
   EG 2026, que tienen la misma estructura de respuesta.

## Recordatorio de llave

La llave canónica del pipeline es `codigo_onpe`, no la posición. El flujo distrital
solo devuelve `codigoAgrupacionPolitica`. `adPosicion` se usa una sola vez.

## Criterios de aceptación

- Cobertura del 100% de las organizaciones con lista inscrita.
- El choque de denominación (id_jne 14 vs 3045, "Partido Democrático Somos Perú")
  está desambiguado y documentado.
- Las dos rutas coinciden en toda fila, o cada discrepancia está revisada a mano.
- El ensayo contra EG 2026 cierra en menos de diez minutos.
- El detector de corrimientos tiene test que lo dispara con un caso construido.
