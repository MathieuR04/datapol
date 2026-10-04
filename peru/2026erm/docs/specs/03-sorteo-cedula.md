# Fase 03 — Sorteo de ubicación en cédula (PRIORIDAD ABSOLUTA)

**Fecha del sorteo: martes 18 de agosto de 2026.** Evento irrepetible.

## Objetivo

Capturar el resultado de los sorteos y construir la tabla `id_jne → posicion`,
que es la primera mitad del puente de organizaciones políticas.

## Contexto normativo

RJ 000098-2026-JN/ONPE. Ver `shared/REGLAS-ELECTORALES.md`, sección del sorteo,
para la mecánica completa. Lo esencial:

- Sorteos **simultáneos**: uno nacional de partidos en la sede central de la ONPE,
  y uno de movimientos regionales en cada ODPE de capital de departamento, más
  Callao y **Huaura**.
- Si en una jurisdicción no se inscribió ningún movimiento, **no hay sorteo**. Con
  23 movimientos regionales concentrados en pocas regiones, varias ODPE no
  sortearán.
- Las alianzas van al bloque nacional o regional **según su alcance**.
- Resultados publicados en la web de la ONPE y en el frontis de cada ODPE. Se
  emite acta en cuatro ejemplares.

## Tareas

1. **Antes del 18.** Prepara el scraper y la estructura de la tabla. Identifica
   dónde publica la ONPE los resultados del sorteo (la RJ dice "página web de la
   ONPE"; localizar la sección exacta).
2. **El 18 y los días siguientes.** Captura el resultado de los 1 + hasta 26
   sorteos. Guarda el HTML o PDF crudo en `data/raw/sorteo/` con fecha.
3. Construye `data/reference/cedula.csv`:
   `version_fecha, bloque, ubigeo_sorteo, posicion, id_jne, correlativo_alfabetico,
   nombre_publicado`
   - `ubigeo_sorteo`: `000000` nacional; ubigeo de departamento para regionales.
     Huaura corresponde a la región Lima provincias.
   - `bloque`: `partidos` o `movimientos`.
4. **Empareja `nombre_publicado` con `id_jne`** contra el padrón de organizaciones
   (fase 05). Son ~74 filas. Se hace a mano si hace falta; hay semanas de margen.
   **Cuidado con el choque exacto de denominación**: id_jne 14 (Partido) e id_jne
   3045 (Alianza) se llaman igual, "Partido Democrático Somos Perú". Desambiguar
   por bloque y por alcance, no por nombre.
5. **Registra el correlativo alfabético** si la publicación lo expone. Es la
   hipótesis de qué termina siendo `adAgrupacionPolitica`. Si no lo expone,
   recalcúlalo ordenando alfabéticamente por denominación dentro de cada bloque y
   guárdalo como `correlativo_alfabetico_calculado`.

## Vigilancia posterior (hasta el 4 de octubre)

Art. 6: si una organización no logra inscribir su lista, se retira o desiste, su
ubicación la toma la de la posición inmediata inferior y **todo lo de abajo se
corre**.

- `cedula.csv` se versiona con `version_fecha`. **Nunca se sobrescribe.**
- Reverifica contra la cédula final publicada antes del 4 de octubre y emite una
  versión nueva por cada cambio detectado.
- El pipeline debe **detectar corrimientos** el día de la elección: si el número de
  organizaciones de un bloque difiere entre `cedula.csv` y lo que reporta la ONPE,
  todas las posiciones bajo la exclusión están desplazadas.

## Criterios de aceptación

- Todos los sorteos realizados están capturados, con el crudo archivado.
- Toda fila tiene `id_jne` resuelto, y el choque de denominación está desambiguado
  explícitamente y documentado.
- El número de filas del bloque `partidos` coincide con el número de partidos y
  alianzas nacionales del padrón; ídem por región para movimientos.
- `docs/sorteo.md` reporta qué ODPE sortearon, cuáles no y por qué.
