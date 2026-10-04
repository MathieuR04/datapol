# Fase 02 — Escaños por circunscripción

`n_escanos` poblado para las 2,118 carreras. Se calcula dentro de
`scripts/build_registro_carreras.py`, junto con el registro, porque es la misma
tabla.

## Resultado

```
Σ consejeros    364    Res. 0001-2026-JNE
Σ regidores  10,842    conteo de candidatos ERM 2026
```

Y la identidad completa cierra:

```
   25 gobernadores + 25 vicegobernadores
+ 364 consejeros
+ 196 alcaldes provinciales + 1,696 alcaldes distritales
+ 10,842 regidores
= 13,148 autoridades en disputa   ✓
```

## Consejeros — desde la resolución

`data/reference/consejeros_2026.csv`, transcripción de la **Res. 0001-2026-JNE**: 201
circunscripciones, 364 consejeros. El mapeo a ubigeo electoral se hace por
`(departamento, provincia)` plegado a ASCII, y en el Callao por distrito contra
`callao_circunscripciones_consejero.csv`.

El único que no cruzaba por nombre era el cercado del Callao (`240101`), porque al no
tener carrera distrital no aparece en el registro de candidaturas y no tiene nombre
ahí. Se resuelve por ubigeo desde la tabla del Callao. Son exactamente los 4 escaños
que faltaban para 364.

## Regidores — desde el conteo de candidatos

**La Res. 0847-2025-JNE no ha sido necesaria.** La spec la plantea como fuente
principal y al conteo de candidatos como validación cruzada; el conteo, solo,
reproduce el objetivo legal exacto.

La regla: la lista de regidores no incluye al alcalde y es de largo par por la ley de
paridad, mientras el número de regidores es impar.

```
n_regidores = max(candidatos a regidor por lista) − 1
```

Se toma el **máximo** sobre todas las listas del concejo porque una lista incompleta
subestima. En 39 de los 1,892 concejos las listas tienen largos distintos, así que la
elección del máximo no es cosmética.

### Por qué se puede confiar en este número

Cuatro comprobaciones independientes, todas exactas:

1. **Σ = 10,842**, que es el valor que exige `shared/REGLAS-ELECTORALES.md` para que
   el total de autoridades dé 13,148. Coincidencia imposible por azar.
2. **Los 1,892 concejos tienen al menos una lista.** Ninguno queda sin dato.
3. **Cero concejos con número par de regidores.** Un par sería aritméticamente
   imposible bajo la regla y delataría un error de conteo.
4. **Todos entre 5 y 15**, salvo Lima Metropolitana con 39, que es la excepción legal.

Distribución, coherente con los rangos de población de la Res. 1229-2006-JNE:

| n_regidores | concejos |
|---|---|
| 5 | 1,577 |
| 7 | 108 |
| 9 | 96 |
| 11 | 78 |
| 13 | 20 |
| 15 | 12 |
| 39 | 1 (Lima Metropolitana) |
| **total** | **1,892** |

Los 1,577 concejos con 5 regidores son la regla de cierre del artículo 2 de la
resolución: todo concejo no listado, o sea de 25,000 habitantes o menos.

### Lo que falta para cerrar la fase del todo

`fuente_n_escanos` dice **`conteo_candidatos_erm2026`**, no la resolución. La spec
pide que las dos fuentes coincidan y que **cada discrepancia se liste
individualmente**. Con una sola fuente eso no se puede hacer.

El riesgo residual es acotado pero real: si en algún concejo **todas** las listas
presentadas fueran incompletas del mismo modo, el máximo subestimaría, y el error
tendría que estar compensado por otro en sentido contrario para que la suma siguiera
dando 10,842. Es poco probable, no imposible.

> **Pendiente:** el PDF de la **Res. 0847-2025-JNE** en `data/raw/resoluciones/`.
> Cuando llegue, cruzar concejo por concejo y listar discrepancias aquí. Mientras
> tanto el pipeline no está bloqueado: hay `n_escanos` para las 2,118 carreras y se
> puede pre-poblar la tabla de autoridades.

## Criterios de aceptación

- [x] Todo `n_escanos` de regidores entre 5 y 15, salvo Lima provincial con 39.
- [x] Todos impares.
- [x] La suma da 10,842 y el total de autoridades da 13,148.
- [x] `fuente_n_escanos` registra de dónde salió cada valor.
- [ ] Las dos fuentes coinciden — falta la resolución para poder compararlas.
