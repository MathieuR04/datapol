# Reglas electorales

Todo lo que el allocator y el forecaster deben codificar.

## Cargos en disputa

| Carrera | N (2026) | Circunscripción | Elige |
|---|---|---|---|
| Gobernador | 25 | departamento | fórmula: gobernador + vicegobernador |
| Consejeros regionales | **201** | provincia; **distrito en Callao** | 1 a 7 consejeros |
| Alcalde y regidores provinciales | 196 | provincia | alcalde + 5 a 15 regidores (Lima 39) |
| Alcalde y regidores distritales | 1,696 | distrito | alcalde + 5 a 15 regidores |

**Por qué 201 y no 196 circunscripciones de consejero:** Lima Metropolitana no
elige consejeros ni gobernador (−1 provincia), y el Callao se subdivide en sus 7
distritos en vez de contar como una provincia (−1 +7). 196 − 1 − 1 + 7 = 201.

Total de consejeros a elegir: **364**. Total de autoridades del proceso: 13,148,
que cierra así:

```
   25 gobernadores + 25 vicegobernadores
+ 364 consejeros
+ 196 alcaldes provinciales + 1,696 alcaldes distritales
+ 10,842 regidores
= 13,148
```

Usa esa identidad como cuadre del registro de carreras.

## Ejecutivo

- **Gobernador:** gana la fórmula con **30% o más** de los votos válidos. Si
  ninguna llega, **segunda vuelta en diciembre** entre las dos primeras.
- **Alcalde provincial y distrital:** mayoría simple. **Sin segunda vuelta, nunca.**

## Regidores — Ley 26864 art. 25 (texto de la Ley 27734)

1. La votación es por lista.
2. A la lista ganadora se le asigna **la cifra repartidora o la mitad más uno de
   los cargos, lo que más le favorezca**, redondeando al entero superior.
3. La cifra repartidora se aplica **entre todas las demás listas participantes**.

La cifra repartidora es D'Hondt: cocientes `votos / d` para `d = 1, 2, 3, …`, se
toman los mayores hasta agotar escaños.

**Verificar en la directiva del JNE del proceso** si existe umbral mínimo para
entrar al reparto. El texto de 1997 mencionaba 5%; el vigente dice "todas las
demás listas participantes". Implementa el umbral como parámetro de configuración
y determina empíricamente cuál reproduce los proclamados de 2022.

## Consejeros regionales — Ley 27683 modificada por Ley 29470

- La circunscripción es la **provincia**. En Callao es el **distrito**.
- El JNE asigna un consejero por circunscripción y distribuye los demás por
  población electoral.
- Donde se elige **un solo consejero, gana el más votado**.
- Donde se eligen **dos o más, cifra repartidora. Sin premio a la mayoría.**

**Para la sección de autoridades electas, el consejo regional se presenta a nivel
de región**: cuántos escaños obtuvo cada organización en el consejo completo. Eso
es la suma de las asignaciones provinciales, pero la asignación se hace por
circunscripción, nunca a nivel regional.

## Composición de listas

Dos formas distintas. Confundirlas rompe el allocator.

**Listas municipales** (provincial y distrital): el candidato a alcalde va
aparte. La lista de regidores **no lo incluye**. Es de largo par por la ley de
paridad, mientras el número de regidores es impar.

```
n_regidores = n_candidatos_regidor − 1
```

Confirmado en la tabla de cuota de la Res. 0847-2025-JNE: 9 regidores, 10
candidatos; 15 regidores, 16 candidatos.

**Listas de consejo regional:** contienen la fórmula de gobernador y
vicegobernador, más, por cada provincia, **el número de consejeros titulares e
igual número de accesitarios**.

```
n_consejeros_provincia = n_candidatos_consejero_provincia / 2
```

**Los accesitarios no se proclaman.** El campo `posicion` debe distinguir titular
de accesitario, o el allocator proclamará suplentes.

## Listas cerradas y bloqueadas

No hay voto preferencial en ERM. Si una lista obtiene k escaños, son los k
primeros **titulares** de esa lista para ese cargo. Por eso `posicion` es un campo
crítico del registro de candidatos.

## Reglas transversales

- Las listas con estado **IMPROCEDENTE, EXCLUIDO o retirada** a la fecha de la
  elección **cuentan votos pero no reciben escaños**. Filtrar por estado histórico
  a esa fecha, no por estado actual.
- **Empates:** la ley los resuelve por sorteo. El allocator debe **detectar y
  marcar** el empate, nunca desempatar arbitrariamente.
- **Distritos capital de provincia (196):** no eligen alcalde distrital.
- **Lima Metropolitana:** no elige gobernador ni consejeros.
- La proclamación definitiva la hace el **JEE**, semanas después. Es un estado
  distinto de "proyectado" y de "electo".

## Fuentes normativas del número de escaños (ERM 2026)

- **Consejeros:** Resolución N.º 0001-2026-JNE, del 2 de enero de 2026.
  Transcrita en `2026/data/reference/consejeros_2026.csv`.
- **Regidores:** Resolución N.º 0847-2025-JNE, del 31 de diciembre de 2025.
  Regla de cierre (art. 2): a toda provincia o distrito **no listado** le
  corresponden **5 regidores**, por tener 25,000 habitantes o menos.
- Rangos de población (Res. 1229-2006-JNE, vigentes desde 2006):

| Población | Regidores |
|---|---|
| 500,001 a más | 15 |
| 300,001 – 500,000 | 13 |
| 100,001 – 300,000 | 11 |
| 50,001 – 100,000 | 9 |
| 25,001 – 50,000 | 7 |
| 25,000 o menos | 5 |

Excepción: Municipalidad Metropolitana de Lima, 39 regidores.

Para **ERM 2022** hay que conseguir las resoluciones equivalentes de ese proceso.
No sirven las de 2026.

## Sorteo de ubicación en cédula — RJ 000098-2026-JN/ONPE

Mecánica (Anexo 1, art. 5), por bloque:

1. Se ordenan alfabéticamente las organizaciones según su denominación.
2. Se asigna un **correlativo desde 1 según ese orden alfabético**.
3. Los bolillos llevan esos correlativos.
4. Se extraen uno a uno: el primero ocupa el primer lugar del bloque, y así.

Son dos objetos distintos generados en el mismo acto: el **correlativo
alfabético** y la **posición sorteada**.

Sedes (art. 2): partidos en la sede central de la ONPE, un solo sorteo nacional;
movimientos regionales en las ODPE de capitales de departamento, más **Callao y
Huaura**. Si en una jurisdicción no se inscribió ningún movimiento, no hay sorteo
(art. 1). Las alianzas van a un bloque u otro **según su alcance** (art. 4).

Bloques (sorteo del 10 de junio de 2026): **partidos arriba, movimientos abajo**.

### Art. 6 — riesgo crítico

Si una organización no logra inscribir su lista, se retira o desiste, **su
ubicación la toma íntegramente la de la posición inmediata inferior**, corriendo
hacia arriba toda la fila para que no queden espacios en blanco.

Consecuencias:

- La tabla `id_jne → posicion` **no queda congelada el 18 de agosto**. Se congela
  cuando se imprime la cédula.
- Hay que **reverificar el puente antes del 4 de octubre** contra la cédula final,
  y otra vez el domingo contra `adPosicion`.
- El pipeline debe **detectar corrimientos**: si el número de organizaciones de un
  bloque difiere entre la tabla del sorteo y lo que reporta la ONPE, todas las
  posiciones bajo la exclusión están desplazadas. Error silencioso y sistemático.
