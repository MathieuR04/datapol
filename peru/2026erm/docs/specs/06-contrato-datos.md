# Fase 06 — Contrato de datos

## Objetivo

Congelar el esquema JSON que consume el frontend, para que pipeline y página se
construyan en paralelo y para que el día de la elección nada dependa de un cambio de
forma.

**Se congela antes de escribir una línea de frontend.**

Estructura de archivos, cortes y reglas en `shared/ARQUITECTURA.md` sección 8.

## Contenido de `carrera/{race_id}.json`

```
meta          race_id, cargo, ubigeo, nombres, escanos, umbral, estado
computo       actas contabilizadas / procesadas / por procesar / observadas,
              electores, emitidos, validos, blancos, nulos, impugnados,
              participacion, ts
resultados[]  organizacion: codigo_onpe, id_jne, nombre, logo, posicion_cedula,
              votos, pct_validos, pct_emitidos, candidato_ejecutivo
proyeccion    por organizacion: p_primero, y para gobernador p_gana_1v y p_pasa_2v;
              escanos p10/p50/p90 y escanos_garantizados; p_segunda_vuelta;
              pct_electorado_locales_frios; capa_usada; ts
autoridades   ejecutivo y proporcionales, con estado por autoridad:
              por_definir | proyectado | electo | proclamado
desagregado[] por ubigeo inferior: votos por organizacion y avance de actas
```

## Reglas

- **Separar lo estático de lo vivo.** Nombres, fotos y logos no viajan en cada
  actualización.
- **Todo objeto lleva su propio timestamp.** Cómputo y proyección se actualizan en
  ciclos distintos y el frontend debe mostrar la antigüedad de cada uno.
- **Publicación atómica.** El manifiesto con la versión del ciclo se escribe al
  final. Un ciclo a medias nunca queda visible.
- **Nulos explícitos.** Sin proyección todavía, el campo es `null` y el frontend
  muestra "sin proyección", nunca un cero.
- Los cuatro estados de autoridad viajan como cadena, no como booleano.

## Salidas

- `specs/schema/*.json`: JSON Schema de cada archivo.
- Archivos de ejemplo llenos con datos reales de ERM 2022, para desarrollar el
  frontend sin pipeline.
- Validador que corre en CI contra todos los archivos publicados.

## Criterios de aceptación

- Cada tipo de archivo tiene esquema y ejemplo real.
- El validador rechaza campos faltantes y tipos incorrectos.
- El archivo de provincia más pesado queda bajo 300 KB sin comprimir.
