# Fase 05 — Replay y umbrales de llamada

## Objetivo

Reproducir la noche del 2 de octubre de 2022 acta por acta, correr el forecaster en
cada corte, puntuar y **elegir empíricamente los umbrales de llamada**.

Constrúyelo temprano, con un forecaster tonto si hace falta. Es el instrumento de
medición del proyecto; sin él, cada cambio de modelo es una opinión.

## Motor

1. Ordena las mesas por la hora de llegada sintética (fase 03).
2. Cortes cada 5 minutos de tiempo simulado.
3. En cada corte, expone al forecaster solo las mesas ya llegadas.
4. Log append-only de proyección, llamadas y estado.

Como el orden es sintético, genera **varios órdenes plausibles incluidos escenarios
adversos**. Si el modelo aguanta bajo los más duros, sirve.

## Métricas

**Calibración.** Cobertura empírica de los intervalos del 50%, 80% y 95%, por decil
de avance y tipo de carrera. Si el intervalo del 80% cubre el 60% de las veces, el
modelo miente y hay que ensancharlo.

**Discriminación.** Brier de `p_primero`, por decil de avance.

**Llamadas.** Para cada par (umbral, avance mínimo): carreras llamadas, llamadas
incorrectas, distribución del tiempo hasta la llamada, porcentaje llamado antes de
las 22:00.

**Escaños.** Acierto del reparto proyectado contra el final, por posición.

## Multiplicidad: el punto central

Llamar 1,900 carreras con umbral de 99.5% produce ~9 errores esperados. Con 99.9%,
~2. Un error en una carrera visible cuesta más que 1,800 aciertos.

1. **El umbral se elige del replay, no de la teoría.** La probabilidad que reporta un
   modelo en la cola del 99.9% no es real hasta calibrarla. Busca el par
   (probabilidad, avance mínimo) con cero errores en 2022 y 2018, y añade margen.
2. **Umbrales por saliencia.** Las 25 gobernaciones, Lima, Callao, Arequipa,
   Trujillo, Cusco y Piura con umbral conservador. Distritos chicos con umbral
   agresivo. La lista de alta saliencia va en configuración, no en el código.

## Los tres estados de una carrera

1. **Probabilidad.** Desde la primera acta, siempre visible, siempre con el
   porcentaje contado al lado. Es el producto principal, no un preámbulo.
2. **Proyectado ganador.** Umbral calibrado, explícitamente reversible.
3. **Electo.** Irreversible: imposibilidad matemática (si todos los votos pendientes
   fueran para el segundo, el primero igual gana) o proclamación del JEE.

El marcador nacional agregado ("612 alcaldías proyectadas, 44 electas, 1,040 en
disputa") es el objeto que se comparte y se actualiza solo.

Publicar el número de **errores esperados** junto al de llamadas ("812 proyecciones,
0.4 errores esperados") protege más que cualquier umbral: si falla una, ya estaba
anunciada.

## Salidas

- `docs/calibracion.md`: curvas de calibración, Brier por decil, tabla de umbrales
  candidatos con llamadas y errores, y la recomendación final.
- `data/reference/umbrales.yaml`: umbrales elegidos por tipo de carrera y saliencia.
- Artefacto de replay reproducible: mismo input y semilla, mismo output.

## Criterios de aceptación

- Cobertura empírica dentro de 5 puntos porcentuales de la nominal en todos los
  deciles. Si no, el forecaster vuelve a la fase 04.
- Existe al menos un par (umbral, avance mínimo) con **cero llamadas incorrectas** en
  2022 y 2018 que llama **más del 60% de las carreras antes de las 22:00**.
  Si no existe, el modelo no está listo, **y el reporte debe decirlo claramente en
  vez de bajar el estándar.**
