# Fase 07 — Frontend

## Objetivo

Renderizar las ~2,100 carreras con las tres secciones, más el resumen nacional.
HTML y JS vanilla, sin framework ni build step, consistente con datapol.lat.

Se construye contra los datos de ERM 2022 y se porta a 2026 en la fase 08.

## Vistas

**Resumen nacional.** Carreras ganadas por organización y nivel (gobernaciones,
provinciales, distritales). Tres mapas nacionales. Marcador de estados: proyectadas,
electas, en disputa. Zoom a una región sin peticiones adicionales, porque el archivo
viene anidado por departamento. Es el objeto compartible y el que más tráfico va a
recibir; optimízalo primero.

**Página de carrera.** Tres secciones:

1. *Resultados.* Mapa desagregado al nivel inferior, barras por organización,
   participación, válidos, blancos, nulos, impugnados, avance de actas. Para
   carreras regionales hay **dos bloques**: gobernador y consejeros, que son
   carreras ONPE distintas (`01` y `02`).
2. *Proyección.* Probabilidades por candidato con el porcentaje contado **siempre
   visible al lado**. Para gobernador, tres números: gana en primera, pasa a
   segunda, y probabilidad de que haya segunda vuelta.
3. *Autoridades electas.* Ejecutivo y cuerpo proporcional, con nombre, foto y enlace
   a la ficha. Los cuatro estados visualmente distinguibles. Desde el minuto cero la
   tabla está completa con todos los escaños en "por definir".

**Consejo regional.** Se muestra a nivel de región: composición del consejo, escaños
por organización, sumando las asignaciones provinciales. Antes de que haya
proyección, muestra el **reparto aplicado al corte actual**, marcado explícitamente
como reparto al corte y no como proyección.

**Distritos capital de provincia** (`estado = sin_eleccion`): página propia que
explica que no eligen alcalde distrital y remite a la carrera provincial.

## Restricciones

- Toda la vista se arma desde los JSON del contrato. **Cero lógica de negocio en el
  cliente**: el frontend no calcula cifra repartidora ni probabilidades.
- Una página de carrera carga con dos peticiones: el estático de candidatos y el
  vivo de la provincia.
- Funciona sin JavaScript para lo básico, o degrada con un mensaje claro. Buena parte
  del tráfico de una noche electoral en provincias viene de conexiones malas.
- Sondeo con intervalo configurable **y jitter**, para no producir picos
  sincronizados.
- Diseño móvil primero.

## Criterios de aceptación

- Las ~2,100 carreras de 2022 renderizan desde datos reales.
- La página de resumen carga en menos de 2 segundos en 3G simulado.
- Prueba de carga contra el objetivo de 20,000 usuarios concurrentes.
- Toda cifra mostrada es trazable a un campo del contrato de datos.
