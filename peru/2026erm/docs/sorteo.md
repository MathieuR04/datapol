# Fase 03 — Sorteo de ubicación en cédula

**Martes 18 de agosto de 2026.** Evento irrepetible. Este documento es el
**pre-reporte**, escrito el 12 de agosto: qué se espera, dónde mirar y qué hay
montado. Se completa con lo observado el 18 y después.

## 1. Norma vigente — corrección a la spec

La spec 03 y `shared/REGLAS-ELECTORALES.md` citan **RJ 000098-2026-JN/ONPE**. Esa es
la resolución **original**, publicada en El Peruano y en el portal de la ONPE el 20
de junio de 2026.

Para los sorteos del 18 de agosto rige **RJ 000116-2026-JN/ONPE**, que aprueba las
instrucciones definitivas. Además —dato que no estaba en la spec— **la 116 también
aprueba las instrucciones del sorteo de ubicación de fórmulas para la Segunda
Elección de Gobernador y Vicegobernador Regional 2026**.

> **Pendiente antes del 18:** conseguir el texto de la RJ 000116 y contrastar su
> Anexo con la mecánica transcrita en `shared/REGLAS-ELECTORALES.md`. Si la 116
> cambió el procedimiento (orden alfabético, correlativos, bloques), hay que
> actualizar ese documento. No se ha podido verificar todavía: se conoce por notas
> de prensa y por el resumen del portal, no por el texto.

Lo que sí está confirmado y no cambia:

- Sorteos **simultáneos**: partidos en la sede central de la ONPE (uno nacional),
  movimientos regionales en las ODPE de capitales de departamento, **más Callao y
  Huaura**.
- Participan las organizaciones que **solicitaron la inscripción de sus candidaturas
  ante los JEE**.
- Las alianzas van a un bloque u otro **según su ámbito**: alcance nacional al bloque
  de partidos, alcance departamental al de movimientos.
- **Partidos arriba, movimientos abajo**, definido en el sorteo de bloques del 10 de
  junio (se sorteó 1 = movimientos, 2 = partidos, y salió ese orden).
- Asisten notarios, Reniec, JNE/JEE, Defensoría del Pueblo, observadores y personeros.

No se ha podido confirmar la **hora** de los sorteos ni si hay transmisión en vivo.

## 2. Dónde publica la ONPE

El portal institucional **devuelve 403 a clientes HTTP estándar**: es el WAF de
CloudFront que documenta `shared/API-ONPE.md`. Con `curl_cffi` e impersonación de
Chrome responde 200. No es opcional aquí tampoco.

Sitio dedicado: **`https://erm2026.onpe.gob.pe/`**, con la página
**`/cedula/descarga-tu-cedula/`**, que es de donde cuelgan las cédulas.

Las cédulas se sirven desde un directorio estático:

```
https://www.onpe.gob.pe/modElecciones/elecciones/ERM2026/{nombre}.pdf
```

Tres publicadas al 12 de agosto:

| Archivo | Contenido |
|---|---|
| `Cedula-Regiones-provincias-Callao.pdf` | Regional/provincial y Callao |
| `Cedula-Regiones-distritos-no-capital-provincia.pdf` | Distrital fuera de capital de provincia |
| `cedula-cercado-de-lima.pdf` | Cercado de Lima |

Son **PDF con texto real, no escaneos** (462 KB el primero, `%PDF-1.5`, con fuentes
incrustadas y sin objetos de imagen). Llevan una marca de agua "RENIEC JNE ONPE"
que ensucia la extracción de texto y hay que filtrar al parsear.

**El servidor devuelve `ETag` y `Last-Modified`.** La versión actual es del **3 de
agosto de 2026, 19:00 GMT**, o sea pre-sorteo: son los diseños, todavía sin el orden
definitivo. Eso da una forma barata y exacta de detectar el momento en que la ONPE
publique la cédula con el resultado del sorteo.

## 3. Qué está montado

`scripts/watch_sorteo.py` — vigila y **archiva**, no parsea. El formato en que la
ONPE publique el acta del 18 no se conoce de antemano, así que el script captura el
crudo tal cual y avisa qué cambió; el parseo se hace después contra lo archivado
(regla 4: la descarga no se puede rehacer).

```
uv run python scripts/watch_sorteo.py --verbose      # una ronda
uv run python scripts/watch_sorteo.py --intervalo 900  # cada 15 min
```

- GET condicional con `ETag`/`If-Modified-Since`: un 304 no se vuelve a descargar.
- Crudo a `data/raw/sorteo/AAAA-MM-DD/{clave}_{sello}.{pdf,html}`, nunca sobrescrito.
- Checkpoint atómico en `data/raw/sorteo/.checkpoint.json`, con sha256 por fuente.
- Reporta `CAMBIO` con sha anterior y nuevo, y **delata PDFs no vigilados** que
  aparezcan enlazados en las páginas: si el acta del sorteo se cuelga como un PDF
  nuevo, sale en el reporte sin que haya que saber su nombre.
- Cortesía: 2 s entre peticiones, backoff exponencial, User-Agent con correo.

Las siete fuentes vigiladas están en `data/reference/sorteo_fuentes.csv`, editable
sin tocar código.

> **Acción para el operador, antes del 18:** correr el script al menos una vez para
> **fijar la línea base**. Sin la captura previa no hay con qué comparar y el cambio
> del 18 no se detecta como cambio, sino como primera vista.

## 4. Qué ODPE sortearán, y cuáles no

Calculado sobre el registro de candidaturas del 11 de agosto. **De 26 sedes
regionales posibles, solo 15 tienen algo que sortear.**

Las 26 sedes son las 25 capitales de departamento (Callao incluido, que es
departamento) más Huaura. El art. 1 es explícito: si en una jurisdicción no se
inscribió ningún movimiento, **no hay sorteo**.

### Sortean (15)

| Sede | Organizaciones regionales |
|---|---|
| AREQUIPA | 4 |
| PUNO | 3 |
| TACNA | 3 |
| **HUAURA** (Lima provincias) | 3 |
| AMAZONAS | 2 |
| CAJAMARCA | 2 |
| HUANUCO | 2 |
| MOQUEGUA | 2 |
| ANCASH, AYACUCHO, CUSCO, MADRE DE DIOS, PIURA, SAN MARTIN, TUMBES | 1 cada una |

### No sortean (11)

`APURIMAC`, `CALLAO`, `HUANCAVELICA`, `ICA`, `JUNIN`, `LA LIBERTAD`, `LAMBAYEQUE`,
`LORETO`, `PASCO`, `UCAYALI` — y **LIMA METROPOLITANA**.

Dos observaciones que valen la pena:

**El Callao tiene sede designada y nada que sortear.** La RJ lo nombra
explícitamente como sede, pero no hay ninguna organización de ámbito regional
inscrita en el Callao. Si el 18 la ODPE del Callao emite un acta, es un acta vacía —
o hay una organización que este análisis no ve, y entonces el análisis está mal.

**Lima Metropolitana tampoco sortea; Huaura sí.** Las tres organizaciones regionales
de Lima operan **exclusivamente en las nueve provincias que no son Lima**
(Barranca, Cajatambo, Canta, Cañete, Huaral, Huarochirí, Huaura, Oyón, Yauyos), o
sea la región Lima provincias. Ninguna presenta candidaturas en Lima Metropolitana.
Por eso Huaura es sede separada.

## 5. Composición de los bloques

74 organizaciones: 41 partidos, 23 movimientos regionales, 10 alianzas.

**Bloque de partidos (nacional): 46** = 41 partidos + 5 alianzas de alcance nacional.
**Bloque de movimientos: 28** = 23 movimientos + 5 alianzas de alcance departamental.

Ningún movimiento regional presenta candidaturas en más de un departamento, lo que
confirma que su ámbito es limpio.

### Las alianzas, por ámbito observado

| id_jne | Alianza | Deptos. | Bloque |
|---|---|---|---|
| 3040 | RENOVACION POPULAR PERU | 24 | partidos |
| 3028 | ALIANZA ELECTORAL VENCEREMOS | 22 | partidos |
| 3036 | **ALIANZA REGIONAL POR EL PERU** | 9 | **partidos** |
| 3046 | COOPERACION, VERDAD Y HONRADEZ | 7 | partidos |
| 3033 | PARTIDO DE LOS TRABAJADORES Y EMPRENDEDORES PTE PERU | 3 | partidos |
| 3031 | APP - TRABAJA AYACUCHO | 1 (Ayacucho) | movimientos |
| 3032 | APP - LA CHOLITA | 1 (Lima provincias) | movimientos |
| 3034 | ALIANZA RENOVACION POPULAR Y TORO | 1 (Lima provincias) | movimientos |
| 3038 | ASI - JUNTOS POR EL PERU | 1 (Puno) | movimientos |
| 3045 | PARTIDO DEMOCRATICO SOMOS PERU | 1 (Puno) | movimientos |

> **El nombre engaña, tal como advierte la spec.** "ALIANZA **REGIONAL** POR EL PERU"
> opera en 9 departamentos: por ámbito va al bloque **nacional**. Clasificar por
> nombre la habría mandado al bloque equivocado. Esta tabla es una hipótesis derivada
> de las candidaturas presentadas y **hay que verificarla contra el acta del sorteo**,
> no al revés.

### El choque de denominación se resuelve solo

`ARQUITECTURA.md` advierte que id_jne 14 y 3045 se llaman igual, "Partido Democrático
Somos Perú", y que el nombre no puede desambiguarlas. Por ámbito **caen en bloques
distintos**:

- **id_jne 14** — partido, 23 departamentos → bloque de partidos, sorteo nacional.
- **id_jne 3045** — alianza, solo Puno → bloque de movimientos, sorteo de Puno.

O sea que en la cédula nunca compiten por la misma posición, y `(bloque,
ubigeo_sorteo)` los separa sin ambigüedad. Es una desambiguación mucho más firme que
el emparejamiento por nombre.

## 6. Correlativo alfabético esperado — bloque de partidos

La mecánica ordena alfabéticamente por denominación y numera desde 1; los bolillos
llevan ese correlativo. Esta es la predicción para las 46 del bloque nacional, para
contrastar contra lo que publique la ONPE:

| # | id_jne | Denominación |
|---|---|---|
| 1 | 4 | ACCION POPULAR |
| 2 | 2980 | AHORA NACION - AN |
| 3 | 3028 | ALIANZA ELECTORAL VENCEREMOS |
| 4 | 1257 | ALIANZA PARA EL PROGRESO |
| 5 | 3036 | ALIANZA REGIONAL POR EL PERU |
| 6 | 2173 | AVANZA PAIS - PARTIDO DE INTEGRACION SOCIAL |
| 7 | 2984 | BATALLA PERU |
| 8 | 2982 | COALICION TRANSFORMADORA TIERRA VERDE |
| 9 | 3046 | COOPERACION, VERDAD Y HONRADEZ |
| 10 | 2898 | FE EN EL PERU |
| 11 | 2901 | FRENTE POPULAR AGRICOLA FIA DEL PERU |
| 12 | 3009 | FUERZA CIUDADANA |
| 13 | 1366 | FUERZA POPULAR |
| 14 | 1264 | JUNTOS POR EL PERU |
| 15 | 2933 | LIBERTAD POPULAR |
| 16 | 2930 | PARTIDO APRISTA PERUANO |
| 17 | 2941 | PARTIDO CIVICO OBRAS |
| 18 | 3033 | PARTIDO DE LOS TRABAJADORES Y EMPRENDEDORES PTE PERU - COMUNIDAD POLITICA INKA PERU |
| 19 | 2961 | PARTIDO DEL BUEN GOBIERNO |
| 20 | 2867 | PARTIDO DEMOCRATA UNIDO PERU |
| 21 | 2895 | PARTIDO DEMOCRATA VERDE |
| 22 | 14 | PARTIDO DEMOCRATICO SOMOS PERU |
| 23 | 2857 | PARTIDO FRENTE DE LA ESPERANZA 2021 |
| 24 | 2840 | PARTIDO MORADO |
| 25 | 2956 | PARTIDO PAIS PARA TODOS |
| 26 | 2869 | PARTIDO PATRIOTICO DEL PERU |
| 27 | 2979 | PARTIDO POLITICO ADP |
| 28 | 2985 | PARTIDO POLITICO INTEGRIDAD DEMOCRATICA |
| 29 | 2218 | PARTIDO POLITICO NACIONAL PERU LIBRE |
| 30 | 2932 | PARTIDO POLITICO PERU ACCION |
| 31 | 2925 | PARTIDO POLITICO PERU PRIMERO |
| 32 | 2921 | PARTIDO POLITICO PRIN |
| 33 | 3001 | PARTIDO POLITICO PUEBLO CONSCIENTE |
| 34 | 3005 | PARTIDO POLITICO TODO CON EL PUEBLO |
| 35 | 2943 | PARTIDO POPULAR CRISTIANO - PPC |
| 36 | 3007 | PARTIDO POR EL ENTENDIMIENTO, RECUPERACION Y LA UNIFICACION DEL PERU |
| 37 | 2935 | PARTIDO SICREO |
| 38 | 2944 | PARTIDO UNIDAD Y PAZ |
| 39 | 2924 | PERU MODERNO |
| 40 | 2731 | PODEMOS PERU |
| 41 | 2931 | PRIMERO LA GENTE - COMUNIDAD, ECOLOGIA, LIBERTAD Y PROGRESO |
| 42 | 2967 | PROGRESEMOS |
| 43 | 3040 | RENOVACION POPULAR PERU |
| 44 | 2927 | SALVEMOS AL PERU |
| 45 | 2998 | UN CAMINO DIFERENTE |
| 46 | 2988 | VISION PERU |

Es una **hipótesis**, no un dato. Depende de que la ONPE ordene con el mismo criterio
(mayúsculas sin tildes, comas y guiones ignorados o no, "PARTIDO POLITICO X" indexado
por la P). Si la publicación expone el correlativo, manda ella y esta tabla solo
sirve para detectar discrepancias. Si no lo expone, se guarda como
`correlativo_alfabetico_calculado`, como pide la spec.

## 7. Estructura de `cedula.csv`

Se crea con la primera captura del 18. Versionada por `version_fecha`, **nunca
sobrescrita** (art. 6).

```
version_fecha, bloque, ubigeo_sorteo, posicion, id_jne,
correlativo_alfabetico, nombre_publicado
```

- `ubigeo_sorteo`: `000000` para el nacional; ubigeo de departamento para los
  regionales. **Huaura va como Lima provincias**, no como `140000`.
- `bloque`: `partidos` | `movimientos`.
- Filas esperadas: 46 en el bloque nacional, 28 repartidas entre 15 sedes regionales.

## 8. Checklist del 18

- [ ] Antes del 18: correr `watch_sorteo.py` para fijar la línea base.
- [ ] Antes del 18: conseguir el texto de **RJ 000116** y contrastar la mecánica.
- [ ] Confirmar hora de los sorteos y si hay transmisión.
- [ ] El 18 y días siguientes: rondas del watcher; archivar todo.
- [ ] Construir `cedula.csv` y emparejar `nombre_publicado` → `id_jne` (74 filas, a
      mano si hace falta).
- [ ] Contrastar contra el correlativo alfabético predicho de §6.
- [ ] Verificar que las 11 sedes de §4 efectivamente no sortearon, y por qué.
      **Atención especial al Callao**, que tiene sede pero ninguna organización.
- [ ] Verificar el bloque de cada alianza contra el acta, en especial id_jne 3036.
- [ ] Completar este documento con lo observado.
