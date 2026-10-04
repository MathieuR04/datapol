# Fase 08 — Portar a 2026

## Objetivo

Mover el software construido contra ERM 2022 al proceso 2026, y cerrar el ensayo
general (`2026/specs/07-prepoblado-y-ensayo.md`).

## Qué se porta y qué no

**Se porta tal cual** (debe ser agnóstico al proceso por diseño): allocator,
forecaster, motor de replay, generador del contrato de datos, frontend.

**Se reemplaza**: registros (`distritos`, `carreras`, `mesas`, `organizaciones`,
`listas`, `candidatos`), crosswalk, y el **cliente de ingesta**, porque 2026 usa
`presentacion-backend` y 2022 usa la API vieja de `/v1/`. Son dos clientes distintos
y siempre lo fueron.

**Se recalibra**: los umbrales de llamada, si algo del proceso 2026 sugiere que el
comportamiento de llegada cambió.

## Checklist de portabilidad

Si algo de esta lista falla, el problema está en el bloque 2022, no aquí:

- [ ] Ningún módulo tiene el año o el nombre del proceso hardcodeado.
- [ ] Rutas base, `idProcesoElectoral` y segmentos de proceso son configuración.
- [ ] El allocator no asume 1,694 ni 1,696 carreras distritales: las lee del registro.
- [ ] El forecaster no asume el conjunto de organizaciones: lo lee del crosswalk.
- [ ] El contrato de datos no cambia entre procesos.
- [ ] El frontend no tiene ubigeos ni nombres de organización hardcodeados.

## Diferencias que sí hay que manejar

- **1,696 carreras distritales en 2026**, 1,694 en 2022. Alto Trujillo y Santa Rosa.
- **Código 82, votos impugnados**, existe en el sistema nuevo y no en 2022.
- **`lineaTiempo` disponible en vivo** en 2026. El forecaster puede usar la hora de
  llegada y la etapa del pipeline como señal, cosa imposible en 2022.
- **Escaños distintos**: resoluciones 0001-2026-JNE y 0847-2025-JNE.
- **Segunda vuelta regional en diciembre**: las URLs y el esquema deben soportar un
  segundo evento.

## Criterios de aceptación

- El pipeline completo corre contra 2026 sin cambios de código, solo de configuración
  y registros.
- El ensayo general de `2026/specs/07` pasa.
- `docs/portabilidad.md` documenta cada punto del checklist y cada diferencia
  manejada.
