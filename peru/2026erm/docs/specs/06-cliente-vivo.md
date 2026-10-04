# Fase 06 — Cliente en vivo

## Objetivo

El scraper que va a correr el 4 de octubre. Se construye y se ensaya contra
`resultadohistorico-eg2026.onpe.gob.pe`, que corre el mismo backend.

Lee `shared/API-ONPE.md` antes de empezar.

## Dos flujos

**Flujo A, agregado, cada 60–90 s.** Un par de peticiones por circunscripción
sobre `resumen-general/totales` y el endpoint de participantes. Alimenta mapas,
resultados, participación y avance. Clasifica cada carrera en `resuelta`,
`competitiva` o `dormida`.

**Flujo B, mesa, cola incremental.** `actas/buscar/mesa?codigoMesa=NNNNNN`. Una
petición devuelve **todas** las elecciones de esa mesa, así que el barrido es del
orden del número de mesas (89,935), no de mesas por tipo. Barrido completo inicial;
después solo actas cuyo estado no es `C`.

## Reglas de implementación

- **`curl_cffi` con impersonación de Chrome.** Sin eso el WAF devuelve cuerpos
  vacíos. No es negociable.
- **Enumeración por rango**: `000001`–`084992` y `900001`–`904943`. HTTP 204 = la
  mesa no existe. Confirma los rangos en producción el mismo día antes de barrer.
- **Autodescubrimiento de `idEleccion`**: viene en cada objeto acta. Mapea
  `idEleccion` → tipo de carrera desde las primeras mesas y guárdalo en
  `data/reference/`. **No lo hardcodees.**
- **Preserva `lineaTiempo` completo.** Es el insumo de trayectorias y del propio
  forecaster (se sabe cuándo llegó cada acta y en qué etapa está). Una vez perdido
  no se recupera.
- **`ever_observada` es monótona.** Una vez verdadera, nunca vuelve a falsa aunque
  el acta llegue a `C`.
- **Guarda de atomicidad.** Si un acta viene en estado `C` con emitidos mayores a
  cero pero sin desglose de votos, se rechaza la fila entera y la mesa queda
  pendiente. Escribir una fila `C` con ceros hace que el modo incremental la salte
  para siempre.
- **Checkpoint y reanudación.** El proceso debe poder morir y continuar sin perder
  trabajo ni repetir peticiones.
- **Crudo inmutable** en `data/raw/` antes de parsear.
- Backoff: 429 espera larga, 503 espera media, pausa periódica por bloque.

## Ensayo obligatorio

Corre el cliente completo contra el sitio de EG 2026 y reporta en
`docs/cliente-vivo.md`: tiempo del barrido completo, tiempo de un ciclo
incremental, tasa de error, número de 429 y 503, y si el flujo A de ~2,100
circunscripciones cabe en 90 segundos con la concurrencia elegida.

## Criterios de aceptación

- El cliente completó un barrido real contra EG 2026 con métricas reportadas.
- Sobrevive a una interrupción forzada y reanuda sin repetir peticiones ni perder
  filas.
- Las respuestas crudas quedan archivadas y el parseo se puede rehacer desde cero
  sin volver a la red.
- Los scripts corren desde terminal con argumentos, sin prompts.
