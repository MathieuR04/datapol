# Fase 04 — Mesas, locales y asignación a carreras

## Objetivo

Construir `mesas.csv`: la terna mesa → local de votación → distrito, para las
89,935 mesas. De ahí sale, por join contra `distritos.csv`, qué mesas pertenecen a
qué carrera.

## Lo que ya está establecido

- **89,935 mesas** en dos rangos densos: `000001`–`084992` (84,992 nacionales) y
  `900001`–`904943` (4,943 especiales). Suman exactamente la cifra oficial, así que
  no hay huecos internos.
- La última mesa del rango normal está en **PURÚS (250401), Ucayali**, el ubigeo más
  alto. La última del rango 900k está en **BOQUERÓN (250206), Padre Abad, Ucayali**.
- **La numeración es monótona en ubigeo.** Esa es la propiedad que hace barato todo
  lo demás.
- En ERM no hay voto en el extranjero. El rango 900k es doméstico especial;
  caracterizar qué es exactamente contra ERM 2022.

## Estrategia: fronteras, no consultas individuales

Mesa → distrito no son 89,935 consultas, son **1,896 fronteras**. Si se conoce el
número de mesas por distrito, las fronteras salen de una suma acumulada en orden de
ubigeo, sin una sola consulta.

El trabajo real es acotar y verificar esas fronteras.

## Paso 1 — Caracterizar `consultaelectoral.onpe.gob.pe`

**Antes de construir nada, investiga qué devuelve exactamente.**

Según el operador, la consulta de miembro de mesa **funciona para todos los DNI** y
devuelve **número de mesa y distrito**, aunque no el local de votación. Verifícalo
con una decena de DNIs de candidatos, que son públicos.

Documenta en `docs/consulta-electoral.md`: endpoint real, parámetros, esquema de
respuesta, si hay captcha o rate limiting, y **qué campos devuelve exactamente**.

Si confirma mesa + distrito para cualquier DNI, ya alcanza para clavar las
fronteras y asignar cada mesa a su carrera, aunque falte el local.

## Paso 2 — Fronteras por distrito

Con `n_mesas` por distrito (fase 01) más la monotonía en ubigeo, genera las
fronteras candidatas. Verifícalas con consultas de DNI: unas pocas por distrito,
concentradas cerca de las fronteras estimadas.

Restricciones que ayudan: contigüidad (los rangos no se solapan ni dejan huecos),
monotonía, y la suma total de 89,935.

Los candidatos a regidor distrital deben ser electores del distrito por requisito
de residencia, así que su mesa cae dentro del rango de ese distrito. Hay ~100 mil
DNIs de candidatos cubriendo los 1,896 distritos.

## Paso 3 — Local de votación

Cuando la ONPE abra **"consulta tu local de votación"**, que sí funciona para los
26.3 millones de electores, se obtiene la terna completa mesa-local-distrito.

El local es la unidad clave de la capa 2 del forecaster: las mesas de un mismo
local son casi intercambiables, así que agruparlas reduce mucho la incertidumbre
temprana.

Si el servicio no abre a tiempo, el respaldo es que la API en vivo trae
`codigoLocalVotacion` en cada acta. Eso llega el mismo domingo, así que la capa 2
arrancaría con retraso pero funcionaría. **No es bloqueante.**

## Privacidad

Deriva únicamente las **fronteras agregadas** y el catálogo de locales. **No
guardes ni publiques la mesa de personas concretas.** El DNI del candidato es
público; dónde vota no es lo que interesa y publicarlo trae un problema
innecesario.

Los datos intermedios con DNI van a `data/interim/` y quedan fuera de git.

## Criterios de aceptación

- `mesas.csv` cubre las 89,935 mesas con `ubigeo_distrito` asignado.
- Los rangos por distrito son contiguos, no se solapan y suman 89,935.
- Toda mesa se puede asignar a sus carreras por join contra `distritos.csv`.
- `local_id` poblado, o explícitamente marcado como pendiente con el plan de
  respaldo documentado.
- Ningún archivo versionado en git contiene DNI asociado a mesa.
