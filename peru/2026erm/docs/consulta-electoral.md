# Fase 04, paso 1 — `consultaelectoral.onpe.gob.pe`

Caracterización del 12 de agosto de 2026. **Parcial**: los endpoints están
identificados, el contrato de respuesta no, porque hay un muro que resolver antes.

## Qué es

SPA de Angular. El bundle declara:

```js
{ production: true, apiUrl: "/clv-ciudadano-backend", apiVersion: "v1/api" }
Object.assign(en, { apiUrl: "" })   // se sobreescribe: la API va al mismo origen
```

**CLV = Consulta Local de Votación.** El backend se llama así aunque hoy la app
solo exponga la consulta de miembro de mesa.

## Endpoints

Base: `https://consultaelectoral.onpe.gob.pe/v1/api`

| Método | Ruta | Para qué |
|---|---|---|
| POST | `/busqueda/dni` | Búsqueda por DNI |
| POST | `/consulta/provisional` | Consulta contra el padrón **provisional** |
| POST | `/consulta/definitiva` | Consulta contra el padrón **definitivo** |
| GET | `/croquis/download?local={local}` | Croquis del local de votación |

Constantes del bundle: `token`, `config`, `visited_urls`, `CROQUIS`, `CREDENCIAL`.

Componentes Angular: `app-miembro-de-mesa` y **`app-local-de-votacion`**, con campos
`local_votacion`, `direccion_local`, `contenedor_local`, `mapaLocal`,
`mi_local_votacion_imagen`, `m_mesa`, `dniDatos`.

### Dos cosas que esto adelanta

**El componente de local de votación ya está construido.** En el portal
`erm2026.onpe.gob.pe` el enlace "Conoce tu local de votación" está en el menú pero
**comentado en el HTML**, así que no está habilitado de cara al público. El código
cliente, en cambio, ya existe. Cuando la ONPE lo active, es probable que no haya que
descubrir nada nuevo.

**`/croquis/download` toma un `local` como parámetro, no un DNI.** Si acepta ids
arbitrarios, el catálogo de locales sería enumerable sin consultar a una sola
persona, que es con diferencia la vía más limpia para el paso 3 de la fase 04. **Sin
verificar**: la petición no pasó del muro.

## El muro: AWS WAF con desafío JavaScript

Es un obstáculo **distinto** al que documenta `shared/API-ONPE.md`. Ahí el problema
era el WAF de CloudFront devolviendo cuerpos vacíos, y se resuelve con `curl_cffi` e
impersonación de Chrome. Aquí no alcanza.

`consultaelectoral.onpe.gob.pe` responde **HTTP 202** con una página que carga
`challenge.js` de `token.awswaf.com` y ejecuta:

```js
AwsWafIntegration.getToken().then(() => window.location.reload(true));
```

Hasta que no exista la cookie `aws-waf-token`, **todas** las rutas de `/v1/api`
devuelven 202 con esa página en vez de JSON. Verificado en las cuatro.

Curiosamente el muro no cubre todo el origen: `/consulta-mesa` y los bundles
estáticos (`main-*.js`) responden 200 sin desafío, mientras que `/` , `/inicio` y
todo `/v1/api` responden 202. El desafío está aplicado por ruta.

### Cómo se pasa

Resolver el desafío una vez en un navegador real, extraer la cookie `aws-waf-token`
y reutilizarla desde `curl_cffi`. El token caduca, así que el scraper necesita
detectar el 202 y renovarlo, no asumir que la sesión dura.

**No implementado todavía.** Requiere un navegador con JS, y decidir si vale la pena
o si conviene esperar a que abra "consulta tu local de votación".

## Por qué esto no bloquea la fase 04

El diseño de la fase no depende de este servicio para lo principal. Mesa → distrito
son **1,892 fronteras**, no 89,935 consultas: con `n_mesas` por distrito y la
monotonía de la numeración en ubigeo, las fronteras salen de una suma acumulada. El
portal sirve para **verificar** fronteras, no para enumerarlas.

Lo que sí falta y no se puede derivar: **`n_mesas` por distrito para ERM 2026**.

> **Trampa evitada.** El roll `peru_2026_distrito_electoral_roll.csv` trae
> `num_mesas` por distrito, y tiene los 1,892 distritos exactos. Pero es de **EG
> 2026**, y el número de mesas cambia entre procesos. Usarlo daría fronteras
> plausibles y equivocadas. Por eso el catálogo que se importó a
> `data/reference/distritos_catalogo.csv` excluye a propósito `num_mesas` y
> `num_electores`: solo ubigeos y nombres.

Y el respaldo para el local está documentado en la spec: la API en vivo trae
`codigoLocalVotacion` en cada acta. Si el servicio no abre, la capa 2 del forecaster
arranca el mismo domingo con retraso, pero arranca.

## Privacidad

Cuando se use el servicio, solo se derivan **fronteras agregadas** y el catálogo de
locales. Nada de DNI asociado a mesa en archivos versionados; los intermedios van a
`data/interim/`, que está fuera de git.

## Pendiente

- [ ] Minar un `aws-waf-token` con un navegador y verificar el contrato de
      `/consulta/definitiva`: qué campos devuelve exactamente y si incluye distrito.
- [ ] Probar si `/croquis/download?local={id}` acepta ids arbitrarios. Si sí, el
      catálogo de locales se enumera sin tocar datos de personas.
- [ ] Averiguar la diferencia real entre `provisional` y `definitiva`, y cuál rige
      para el 4 de octubre.
- [ ] Vigilar cuándo se descomenta "Conoce tu local de votación" en
      `erm2026.onpe.gob.pe` — se puede añadir a `sorteo_fuentes.csv` y que lo detecte
      `watch_sorteo.py`, que ya avisa de cambios en esas páginas.
- [ ] Conseguir `n_mesas` por distrito para ERM 2026. Es el insumo que de verdad
      bloquea las fronteras.
