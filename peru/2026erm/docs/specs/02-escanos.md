# Fase 02 — Escaños por circunscripción

## Objetivo

Poblar `n_escanos` en `carreras.csv`. **Es un campo bloqueante**: sin él no hay
reparto, no hay proyección proporcional y no se puede pre-poblar la tabla de
autoridades, porque no se sabe cuántas filas crear.

## Consejeros — resuelto

`data/reference/consejeros_2026.csv` ya contiene la tabla completa de la
Resolución N.º 0001-2026-JNE, transcrita y validada: **201 circunscripciones,
364 consejeros, 25 departamentos**.

Tarea: mapear `departamento, provincia` a ubigeo electoral. Ojo con las siete
filas del Callao, que son **distritos**, no provincias.

## Regidores — a construir

Fuente normativa: **Resolución N.º 0847-2025-JNE**, del 31 de diciembre de 2025.
El PDF lo tiene el operador; pídeselo y guárdalo en `data/raw/resoluciones/`.

Estructura de la resolución:
- Artículo 1: tabla explícita de regidores para concejos con población **mayor a
  25,000 habitantes**.
- **Artículo 2 (regla de cierre): a toda provincia o distrito no listado le
  corresponden 5 regidores.** Esto cubre la mayoría de los 1,896 concejos.
- Excepción: Municipalidad Metropolitana de Lima, 39 regidores.

Rangos usados (Res. 1229-2006-JNE): 15 / 13 / 11 / 9 / 7 / 5 según población.

### Validación cruzada con el registro de candidaturas

De la fase 00 sale una segunda fuente independiente:

```
n_regidores = n_candidatos_regidor − 1
```

La lista de regidores **no incluye al alcalde** y es de largo par por la ley de
paridad, mientras el número de regidores es impar. Confirmado en la tabla de cuota
de la propia resolución: 9 regidores → 10 candidatos; 15 → 16.

Toma el máximo por concejo sobre todas sus listas inscritas (una lista incompleta
podría subestimar) y compara contra la resolución.

Para consejeros, la validación análoga es
`n_consejeros = n_candidatos_consejero_provincia / 2`, porque van titulares más
igual número de accesitarios.

## Cuadre final

```
   25 gobernadores + 25 vicegobernadores
+ 364 consejeros
+ 196 alcaldes provinciales + 1,696 alcaldes distritales
+ Σ n_regidores
= 13,148
```

Es decir, `Σ n_regidores` debe dar exactamente **10,842**.

## Criterios de aceptación

- Todo `n_escanos` de regidores está entre 5 y 15, salvo Lima provincial con 39,
  y es impar.
- La suma da 10,842 y el total de autoridades da 13,148.
- Las dos fuentes (resolución y conteo de candidatos) coinciden. **Cada
  discrepancia se lista individualmente** en `docs/escanos.md` con el ubigeo, el
  valor de cada fuente y una hipótesis. No promedies ni elijas en silencio.
- `fuente_n_escanos` registra de dónde salió cada valor.
