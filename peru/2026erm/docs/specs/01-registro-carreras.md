# Fase 01 — Registro de carreras y distritos

## Objetivo

Construir las dos tablas espinales: `distritos.csv` (1,896 filas) y `carreras.csv`
(~2,118 filas). Esquema completo en `shared/ARQUITECTURA.md` sección 2.

## Método

1. Enumera ubigeos desde `/v1/ERM2026/ubigeos/{tipo}` o desde el registro de
   candidaturas de la fase 00, lo que esté disponible. Cruza ambas fuentes.
2. **Declara las excepciones como datos, no como lógica.** Un archivo de reglas
   explícito produce las columnas `race_*` de `distritos.csv`:
   - Distritos de Lima provincia (`1401xx`): sin gobernador ni consejero.
   - Distritos del Callao: `race_consejero = 02-{ubigeo_distrito}`.
   - Distritos capital de provincia (196): sin carrera distrital.
   - Región Lima provincias: ODPE Huaura, circunscripción regional separada.
3. Nuevos distritos post-2022: **Alto Trujillo** (La Libertad) y **Santa Rosa**
   (Loreto). Total 1,896 distritos, 1,696 con carrera distrital.
4. Puebla `electores_habiles` y `n_mesas` desde la ONPE o desde el padrón.

## Cuadres obligatorios

```
carreras por tipo:  25 gobernador
                   201 consejero    (ver shared/REGLAS-ELECTORALES.md)
                   196 alcalde provincial
                 1,696 alcalde distrital
                 -----
                 2,118 carreras

distritos:       1,896 filas
                   196 con race_distrital nulo (capitales de provincia)
                    43 de Lima provincia sin gobernador ni consejero
                     7 del Callao con race_consejero a nivel distrital

autoridades:    13,148 (ver la identidad en shared/REGLAS-ELECTORALES.md)
mesas:          89,935 (rangos 000001-084992 y 900001-904943)
```

Ninguno de estos números es aproximado. Si tu tabla no da exactamente esto, hay un
error; encuéntralo antes de avanzar.

## Criterios de aceptación

- Los cuadres de arriba dan exacto.
- Ningún `race_id` duplicado.
- Todo distrito tiene al menos una carrera no nula.
- `docs/registro-carreras.md` reporta conteos por nivel y las excepciones
  aplicadas, una por una.
