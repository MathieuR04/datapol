# Fase 00 — Fuentes locales de candidaturas

## Objetivo

Normalizar el registro de candidaturas ERM 2026 que el operador ya descargó, y
montar el snapshot diario que capturará los cambios de estado hasta la elección.

## Insumos

```
/Users/mathieurojas/Documents/datapol/articulos/erm-2026-candidatos/data/
    erm2026_candidatos.csv
    hdv_erm2026.sqlite
```

La ruta exacta del sqlite puede variar; **verifica el contenido del directorio
antes de asumir**. Son de solo lectura: cópialos a `2026/data/raw/` y trabaja
sobre la copia.

## Tareas

1. **Inventario.** Describe el esquema real de ambas fuentes: columnas, tipos,
   cardinalidades, valores distintos de los campos de estado y cargo. Escríbelo en
   `docs/fuentes-locales.md` antes de transformar nada.
2. **Normaliza** a `data/processed/`:
   - `listas.parquet`: `lista_id, race_id, id_jne, expediente, estado_lista,
     fecha_estado`
   - `candidatos.parquet`: `cand_id, lista_id, posicion, cargo, es_accesitario,
     nombres, apellidos, dni, sexo, ubigeo_provincia_consejero, hoja_vida_url,
     foto_url, estado_candidato`
   - `organizaciones.parquet`: `id_jne, nombre_oficial, siglas, tipo_org, ambito,
     ubigeo_ambito`
3. **Deriva `race_id`** de tipo de elección y ubigeo. Ver `shared/ARQUITECTURA.md`.
   Para consejeros, el `race_id` es el de la **provincia que representa** el
   candidato (o el distrito, en Callao), no el del departamento.
4. **Marca accesitarios.** Las listas de consejo regional llevan titulares e igual
   número de accesitarios. Si la fuente no lo distingue explícitamente, dedúcelo
   del orden y del número de consejeros de esa provincia, y **documenta la regla
   usada y su tasa de acierto**. Este campo decide a quién se proclama.
5. **Snapshot diario.** Script que corre el operador (o cron) y guarda una copia
   fechada del estado de listas y candidatos en `data/raw/snapshots/AAAA-MM-DD/`.
   Empieza a correr **hoy** y no para hasta el 4 de octubre.

## Criterios de aceptación

- Toda carrera del registro con listas tiene al menos una lista, y toda lista
  inscrita tiene candidatos.
- Todo candidato tiene `posicion` no nula.
- Todo consejero tiene `ubigeo_provincia_consejero` resuelto y `es_accesitario`
  determinado.
- El snapshot diario corre y produce archivos fechados.
- `docs/fuentes-locales.md` documenta el esquema original, las transformaciones y
  toda anomalía.
