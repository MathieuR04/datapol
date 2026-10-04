# APIs de la ONPE y del JNE

Son dos sistemas distintos de la ONPE que requieren clientes distintos.

## Histórico antiguo — `resultadoshistorico.onpe.gob.pe`

Arquitectura vieja. Sirve ERM 2022 y anteriores.

```
GET /v1/{PROCESO}/ubigeos/{tipo}          -> {departments, provinces, districts}
GET /v1/{PROCESO}/results/{tipo}/{ubigeo} -> {generals, results}
GET /v1/{PROCESO}/mesas/locales/{ubigeo_distrito}
      -> {locales: [{CCODI_LOCAL, CCODI_UBIGEO, TNOMB_LOCAL, TDIRE_LOCAL}]}
GET /v1/{PROCESO}/mesas/actas/{n}/{ubigeo_distrito}/{codigo_local}
      -> {mesasVotacion: [{NUMMESA, PROCESADO, IMAGEN}], TOTAL_PROCESADAS,
          TOTAL_NO_PROCESADAS}
GET /v1/{PROCESO}/mesas/detalle/{numero_mesa}
      -> {procesos: {regional: {gobernador, consejero, votos, resoluciones,
                                imageActa},
                     municipal: {provincial, distrital, votos, resoluciones,
                                 imageActa},
                     asistioNoVoto, realImages},
          lastAct: {FECHA, HORA}}
```

`tipo`: `01` gobernador, `02` consejeros, `03` alcalde provincial, `04` alcalde
distrital. Ubigeo electoral de 6 dígitos.

`generals.generalData`: `ELECTORES_HABIL`, `TOT_CIUDADANOS_VOTARON`,
`POR_ACTAS_CONTABILIZADAS`, `ACTAS_PROCESADAS`, `CONTABILIZA`, `POR_PROCESAR`.

Filas de `results`: `C_CODI_AGP`, `AGRUPACION`, `TOTAL_VOTOS`, `POR_VALIDOS`,
`POR_EMITIDOS`, `ACTAS_COMPUTADA`, `TOTAL_MESAS`, `NLISTA`.

Verificado:

- `mesas/detalle` **devuelve todas las elecciones de esa mesa en una respuesta** y
  solo requiere el número de mesa. Se enumera secuencialmente sin recorrer locales.
- En `mesas/actas` el primer parámetro es el número de mesas del local y se valida
  de forma laxa; cualquier valor de dos dígitos devuelve lo mismo.
- Cada acta trae `TNOMB_LOCAL`, `TDIRE_LOCAL`, `CCENT_COMPU` (centro de cómputo,
  proxy de ODPE), `NNUME_HABILM`, `TOT_CIUDADANOS_VOTARON`, `OBSERVACION`,
  `OBSERVACION_TXT` y `resoluciones`.
- **No hay marca temporal por acta.** Los únicos campos de fecha son
  `lastAct.FECHA` y `lastAct.HORA`, que son el corte final global del proceso.
- Códigos reservados: `80` blancos, `81` nulos. No existe el 82 en 2022.

## Sistema en vivo — `presentacion-backend`

Arquitectura nueva. Corrió en EG 2026 y correrá en ERM 2026 bajo otro subdominio.
Los sitios archivados de esta arquitectura **conservan todo**, incluida la línea de
tiempo. Ejemplo accesible: `resultadohistorico-eg2026.onpe.gob.pe`.

```
GET /presentacion-backend/resumen-general/totales
      ?idAmbitoGeografico=1&idEleccion=N&tipoFiltro=ubigeo_nivel_03
      &idUbigeoDepartamento=..&idUbigeoProvincia=..&idUbigeoDistrito=..

GET /presentacion-backend/eleccion-presidencial/participantes-ubicacion-geografica-nombre
      ?tipoFiltro=..&idAmbitoGeografico=..&ubigeoNivel1=..&ubigeoNivel2=..
      &ubigeoNivel3=..&idEleccion=N
      (el nombre del recurso cambia por tipo de eleccion; descubrirlo en ERM 2026)

GET /presentacion-backend/actas/buscar/mesa?codigoMesa=NNNNNN
```

Verificado:

- **`/actas/buscar/mesa` devuelve todas las elecciones de esa mesa en una sola
  respuesta**, un objeto acta por `idEleccion`. En ERM 2026 una petición trae
  gobernador, consejero, alcalde provincial y alcalde distrital juntos.
- Mesas por **rango secuencial**, no por catálogo. HTTP 204 = la mesa no existe.
- Cada acta trae `codigoLocalVotacion` y `nombreLocalVotacion`. **El local de
  votación no hay que derivarlo.**
- Cada acta trae `lineaTiempo`: cambios de estado con `codigoEstadoActa`,
  `descripcionEstadoActa` y **`fechaRegistro` en milisegundos**. Tres estados:
  `T` Digitalización, `D` Digitación, `C` Contabilizada.
- Cada fila de `detalle` trae tres campos que hay que distinguir:
  `adAgrupacionPolitica` (código ONPE), `adPosicion` (**posición en cédula**),
  `adDescripcion` (nombre oficial completo).
- `idEleccion` se **autodescubre**: viene en cada objeto acta.
- Códigos reservados: `80` blancos, `81` nulos, **`82` impugnados**.

### El WAF bloquea clientes HTTP estándar

CloudFront devuelve cuerpos vacíos a `requests`, `urllib` y `aiohttp`. Usar
`curl_cffi` con `impersonate="chrome124"` o equivalente. **No es opcional.**

Límites observados: 429 exige espera larga (60s+), 503 bajo carga. Con 20 workers,
delay aleatorio de 20–80 ms y pausa de 5 s cada 10,000 peticiones, aguanta. No
subir sin medir.

**Rendimiento medido** (EG 2026 segunda vuelta, `peru/2026eg/segunda/scripts/`):

| Flujo | Volumen | Tiempo | Concurrencia |
|---|---|---|---|
| Distrital (`02a_scrape_distritos.py`) | ~2,000 celdas | **~3 min** | 5 |
| Mesa (`02b_scrape_mesas.py`) | 92,791 mesas | **~15 min** | 20 |

Son ~103 peticiones/s en el flujo de mesa. **Esa es la referencia** para el cliente
en vivo de ERM 2026: el presupuesto de ciclo es de 60–90 s para el flujo distrital,
así que la concurrencia no es comodidad.

Dos detalles de implementación que importan más de lo que parece:

1. **Sesión persistente por worker**, no una por petición. Reutilizar la conexión
   TLS es la mitad del rendimiento.
2. **Nada de trabajo pesado dentro del lock.** Comprimir o parsear bajo el mutex
   serializa a todos los workers esperándose entre sí, y a 20 workers eso es el
   cuello de botella antes que la red. Bajo el lock, solo la escritura.

`resultadohistorico-eg2026.onpe.gob.pe` es el banco de pruebas correcto para el
cliente en vivo: mismo backend, latencias y límites reales.

## El código de agrupación

**No es la posición en cédula y no es estable entre procesos.**

| Organización | ERM 2022 | EG 2026 |
|---|---|---|
| Alianza para el Progreso | 4 | 1 |
| Avanza País | 7 | 7 |
| Fuerza Popular | 6 | 8 |
| Juntos por el Perú | 5 | 10 |
| Somos Perú | 2 | 20 |
| Frente de la Esperanza 2021 | 11 | 21 |
| Partido Morado | 10 | 22 |
| Partido Patriótico del Perú | 141 | 24 |
| Perú Libre | 8 | 27 |
| Podemos Perú | 9 | 32 |
| Renovación Popular | 3 | 35 |

Solo Avanza País coincide, por azar. **Nunca reutilizar un crosswalk entre
procesos.**

En EG 2026 los códigos 7 al 38 están en **orden alfabético estricto** por nombre
oficial; los seis primeros rompen el patrón. Es consistente con el art. 5 de la
RJ 000098-2026-JN/ONPE, que asigna un correlativo alfabético antes de sortear.

## Consulta electoral — `consultaelectoral.onpe.gob.pe`

Servicio de consulta ciudadana por DNI. Según el operador, la consulta de **miembro
de mesa funciona para todos los DNI** y devuelve **número de mesa y distrito**,
aunque no el local de votación. El servicio de "consulta tu local de votación"
abre más cerca de la elección y sí devuelve el local.

Sin caracterizar: hay que investigarlo. Ver `2026/specs/04-mesas-y-locales.md`.

## APIs del JNE

```
GET https://plataformahistorico.jne.gob.pe/Candidato/GetExpedientesLista/{proceso}-{idTipo}-{ubigeo}------0-
```

`proceso` = 113 para ERM 2022. `idTipo`: 4 REGIONAL, 5 MUNICIPAL PROVINCIAL,
6 MUNICIPAL DISTRITAL. Ubigeo electoral.

Devuelve `{data: [...]}` con `idOrganizacionPolitica`, `strOrganizacionPolitica`,
`strTipoOrganizacion`, `strCodExpediente`, `idSolicitudLista`, `strEstadoLista`,
`strJuradoElectoral`, `strUbigeo`, `intCandHombres`, `intCandMujeres`,
`idPlanGobierno`, `strRutaArchivo`.

El array `listaCandidato` viene vacío. Los candidatos salen de otro endpoint que
hay que descubrir capturando el tráfico al pulsar "Ver candidatos".

**Correspondencia de tipos ONPE ↔ JNE:**

| ONPE | JNE `idTipoEleccion` |
|---|---|
| `01` gobernador | 4 |
| `02` consejeros | 4 |
| `03` alcalde provincial | 5 |
| `04` alcalde distrital | 6 |

El JNE une gobernador y consejeros en un solo expediente regional. Separarlos por
`cargo` y por la provincia que representa cada consejero.

**El ubigeo es idéntico en ambos organismos.** Sin tabla de traducción.
