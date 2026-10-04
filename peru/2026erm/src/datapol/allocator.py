"""Reparto de escaños: cifra repartidora peruana y premio a la mayoría.

Función pura. La usan el flujo de mesa —dentro de cada simulación del
forecaster— y el flujo distrital, para el mapa de consejeros al corte.

REGLA DE REGIDORES — Ley 26864 art. 25 (texto de la Ley 27734)
--------------------------------------------------------------
  1. La votación es por lista.
  2. A la lista ganadora se le asigna **la cifra repartidora o la mitad más uno
     de los cargos, lo que más le favorezca**, redondeando al entero superior.
  3. La cifra repartidora se aplica **entre todas las demás listas participantes**.

El punto 3 admite dos lecturas, y dan resultados distintos:

  · `EXCLUYENTE` — los escaños que sobran tras el premio se reparten por D'Hondt
    **solo entre las demás listas**. El ganador se queda exactamente con el
    premio, salvo que D'Hondt sobre todas le diera más.
  · `INCLUYENTE` — se le adjudica el premio al ganador y los escaños restantes van
    a los mayores cocientes que queden, **incluidos los suyos**. Así el ganador
    puede superar el premio sin barrer.

Cuál rige no se decide leyendo: se decide contrastando contra los 1,876 concejos
con proclamación completa de ERM 2022. Ver `docs/allocator.md`.

CONSEJEROS REGIONALES — Ley 27683 modificada por Ley 29470
-----------------------------------------------------------
  · Un solo escaño: gana el más votado.
  · Dos o más: cifra repartidora, **sin premio a la mayoría**.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def premio_a_la_mayoria(n_escanos: int) -> int:
    """«La mitad más uno de los cargos, redondeando al entero superior».

    La redacción admite redondear antes o después de sumar uno. Derivado de los
    1,876 concejos proclamados de ERM 2022, rige **redondear la mitad y sumar
    uno después**: con 5 escaños el ganador se lleva 4, no 3.

        n:      5   7   9  11  13  15  39
        premio: 4   5   6   7   8   9  21
    """
    return math.ceil(n_escanos / 2) + 1


def cocientes(votos: dict[str, int], n: int,
              disponibles: dict[str, int] | None = None
              ) -> list[tuple[float, str, int]]:
    """Cocientes de D'Hondt: (valor, lista, divisor), de mayor a menor.

    `disponibles` limita **cuántos cocientes genera cada lista**: una lista con
    tres candidatos hábiles solo aporta `v/1`, `v/2` y `v/3`. No puede ocupar un
    cuarto escaño porque no tiene a quién sentar, así que ese cociente no debe
    competir. Ausente significa cero.
    """
    salida = []
    for lista, v in votos.items():
        # **Desconocido no es cero.** Si la lista no figura en `disponibles`
        # es que no tenemos su plancha, no que se haya quedado sin candidatos:
        # no hay información, y la ausencia de información no es información
        # (regla 1 de CLAUDE.md). Se reparte sin tope y se marca aparte.
        # En Pucará (Puno) la organización 2702 obtuvo 854 votos y un regidor
        # proclamado sin figurar en el registro de candidaturas del JNE.
        if disponibles is None or lista not in disponibles:
            tope = n
        else:
            tope = min(n, disponibles[lista])
        for d in range(1, tope + 1):
            salida.append((v / d, lista, d))
    # Orden estable: a igual cociente, primero la lista con más votos.
    salida.sort(key=lambda x: (-x[0], -votos[x[1]], x[1]))
    return salida


def dhondt(votos: dict[str, int], n: int,
           disponibles: dict[str, int] | None = None
           ) -> tuple[dict[str, int], int, tuple[str, ...]]:
    """Cifra repartidora pura, sin premio.

    -> (escaños, escaños en empate sin adjudicar, listas empatadas).

    Si el cociente que decide el último escaño está **empatado** con el
    siguiente, ese escaño no se adjudica: la ley lo resuelve por sorteo. Pasó en
    San Pedro de Laraos (Huarochirí), donde dos listas empataron a 37 votos y se
    jugaban el quinto escaño.
    """
    asignados: dict[str, int] = {k: 0 for k in votos}
    coc = cocientes(votos, n, disponibles)
    if len(coc) <= n:
        for _, lista, _ in coc:
            asignados[lista] += 1
        return asignados, 0, ()

    # Frontera: cuántos cocientes valen exactamente lo mismo que el último que
    # entra, y cuántos de ellos caben.
    corte = coc[n - 1][0]
    dentro = [c for c in coc[:n] if c[0] == corte]
    fuera = [c for c in coc[n:] if c[0] == corte]
    if not fuera:
        for _, lista, _ in coc[:n]:
            asignados[lista] += 1
        return asignados, 0, ()

    for _, lista, _ in coc[:n - len(dentro)]:
        asignados[lista] += 1
    empatadas = tuple(sorted({c[1] for c in dentro + fuera}))
    return asignados, len(dentro), empatadas


@dataclass
class Reparto:
    escanos: dict[str, int]
    ganador: str | None
    premio_aplicado: bool
    empate: bool
    # Escaños que no se adjudican porque hay empate exacto de votos entre las
    # listas que se los disputan. La ley los resuelve **por sorteo**, así que
    # inventar un ganador es peor que declarar el empate: en la tabla de
    # autoridades quedan en `por_definir` hasta que el JEE sortee.
    escanos_en_empate: int = 0
    listas_empatadas: tuple[str, ...] = ()
    # Listas que recibieron escaños sin que se conozca su plancha: el escaño se
    # adjudica a la organización, pero no hay a quién sentar. En la tabla de
    # autoridades van con `cand_id` nulo.
    sin_plancha: tuple[str, ...] = ()


def _ganador(votos: dict[str, int]) -> tuple[str | None, bool]:
    if not votos:
        return None, False
    tope = max(votos.values())
    lideres = sorted(k for k, v in votos.items() if v == tope)
    # Un empate en el primer puesto lo resuelve la ley por sorteo: se marca y
    # nunca se desempata a dedo (shared/REGLAS-ELECTORALES.md).
    return lideres[0], len(lideres) > 1


def reparte_concejo(votos: dict[str, int], n_escanos: int,
                    modo: str = "excluyente",
                    disponibles: dict[str, int] | None = None,
                    promovidos: dict[str, int] | None = None,
                    _gana_forzado: str | None = None) -> Reparto:
    """Reparto de un concejo municipal, con premio a la mayoría.

    `modo`: `excluyente` o `incluyente`, las dos lecturas del art. 25.3.

    `disponibles`: candidatos hábiles por lista. **Una lista no puede ocupar más
    escaños que candidatos le quedan en pie.** No lo dice ninguna spec, pero se
    observa en ERM 2022: en 26 concejos la lista ganadora tenía menos regidores
    inscritos que el premio y solo se llevó los que tenía; el resto pasó a las
    siguientes. Con listas cerradas y exclusiones individuales el caso es normal,
    y en 2026 será más frecuente conforme avancen las tachas.

    `promovidos`: cuántos regidores de cada lista subieron a la candidatura a
    alcalde porque el titular cayó. **Solo dejan libre su escaño de regidor si su
    lista gana la alcaldía.** Medido en ERM 2022 sobre 949 promociones:

        la lista GANA la alcaldía  ( 80)  ->  80 son alcalde, 0 salen regidores
        la lista PIERDE            (869)  ->  119 salen electos regidores

    Es decir, la promoción crea una segunda candidatura, no sustituye a la
    primera: si pierde la alcaldía, el promovido conserva su sitio en la plancha.
    Descontarlo siempre rompería el reparto en los 869 casos donde no toca.

    Como el alcalde se elige por mayoría simple, quien gana la alcaldía es la
    misma lista más votada que recibe el premio, así que el descuento se resuelve
    aquí dentro sin necesidad de un segundo pase.
    """
    votos = {k: v for k, v in votos.items() if v > 0}
    if not votos or n_escanos <= 0:
        return Reparto({}, None, False, False)

    ganador, empate = _ganador(votos)

    # EMPATE POR LA ALCALDÍA: EL PREMIO NO TIENE DUEÑO
    # ------------------------------------------------
    # `_ganador` devolvía `lideres[0]` —el código más bajo— y marcaba `empate`,
    # o sea que desempataba a dedo justo donde su propio comentario dice que no
    # se hace. El premio a la mayoría se lo llevaba entero esa lista. En Córculla
    # (Ayacucho) Perú Libre y Movimiento Regional Agua empataron a 83 votos y la
    # página daba 4 de 5 regidores a Perú Libre.
    #
    # Quien gane la alcaldía se lleva el premio, así que mientras el sorteo no
    # ocurra **los escaños que dependen de él no están adjudicados**. Se reparte
    # bajo cada resultado posible del sorteo y se adjudica solo el mínimo: lo que
    # cada lista obtiene pase lo que pase. El resto queda en `escanos_en_empate`.
    if empate and _gana_forzado is None:
        lideres = sorted(k for k, v in votos.items() if v == max(votos.values()))
        partes = [reparte_concejo(votos, n_escanos, modo, disponibles, promovidos,
                                  _gana_forzado=g) for g in lideres]
        piso = {k: min(p.escanos.get(k, 0) for p in partes) for k in votos}
        piso = {k: v for k, v in piso.items() if v > 0}
        return Reparto(piso, None, False, True,
                       n_escanos - sum(piso.values()), tuple(lideres),
                       partes[0].sin_plancha)
    if _gana_forzado is not None:
        ganador = _gana_forzado

    # El promovido ocupa la alcaldía, no su escaño de regidor. Solo aplica al
    # ganador: para las demás listas el promovido sigue en la plancha.
    desconocidas = (() if disponibles is None
                    else tuple(sorted(k for k in votos if k not in disponibles)))

    if disponibles is not None and promovidos:
        cede = promovidos.get(ganador, 0)
        if cede:
            disponibles = dict(disponibles)
            disponibles[ganador] = max(0, disponibles.get(ganador, 0) - cede)

    puro, pend_puro, emp_puro = dhondt(votos, n_escanos, disponibles)
    premio = min(premio_a_la_mayoria(n_escanos), n_escanos)
    if disponibles is not None and ganador in disponibles:
        premio = min(premio, disponibles[ganador])

    def _cierra(escanos, premio_aplicado, pend=0, emp_listas=()):
        con_escano = tuple(k for k in desconocidas if escanos.get(k, 0) > 0)
        return Reparto(escanos, ganador, premio_aplicado, empate or bool(emp_listas),
                       pend, emp_listas, con_escano)

    # «Lo que más le favorezca»: si D'Hondt ya le da más que el premio, manda
    # D'Hondt. Pasa cuando el ganador arrasa —con el 80% de los votos el reparto
    # puro le da más escaños que la mitad más uno—.
    if puro[ganador] >= premio:
        return _cierra(puro, False, pend_puro, emp_puro)

    if modo == "excluyente":
        # El ganador se queda con el premio; el resto por D'Hondt entre las demás.
        escanos = {k: 0 for k in votos}
        escanos[ganador] = premio
        restantes = n_escanos - premio
        otros = {k: v for k, v in votos.items() if k != ganador}
        pend, emp_l = 0, ()
        if restantes > 0 and otros:
            rep, pend, emp_l = dhondt(otros, restantes, disponibles)
            for lista, e in rep.items():
                escanos[lista] = e
        return _cierra(escanos, True, pend, emp_l)

    if modo == "incluyente":
        # Se le adjudica el premio y los escaños restantes van a los mayores
        # cocientes que queden, incluidos los del propio ganador a partir del
        # divisor `premio + 1`.
        escanos = {k: 0 for k in votos}
        escanos[ganador] = premio
        restantes = n_escanos - premio
        if restantes > 0:
            pool = [c for c in cocientes(votos, n_escanos, disponibles)
                    if c[1] != ganador or c[2] > premio]
            for _, lista, _ in pool[:restantes]:
                escanos[lista] += 1
        return _cierra(escanos, True)

    raise ValueError(f"modo desconocido: {modo}")


def aplica_tope(escanos: dict[str, int], votos: dict[str, int],
                n_escanos: int, disponibles: dict[str, int]) -> dict[str, int]:
    """Ninguna lista ocupa más escaños que candidatos hábiles conserva.

    El excedente no desaparece: se reasigna a los mayores cocientes de D'Hondt
    que queden entre las listas que aún tienen sitio. Se itera porque reasignar
    puede desbordar a la siguiente.

    Ausente en `disponibles` significa **cero**, no «sin tope». En Aquía (Áncash)
    Juntos por el Perú ganó la alcaldía con el 67% de los votos y sus cinco
    regidores estaban todos improcedentes: se llevó 0 de los 5 escaños, que
    pasaron íntegros a las otras dos listas.
    """
    tope = {k: disponibles.get(k, 0) for k in votos}
    ajustado = dict(escanos)
    for _ in range(n_escanos + 1):
        sobra = sum(max(0, v - tope[k]) for k, v in ajustado.items())
        if sobra == 0:
            break
        for k in ajustado:
            ajustado[k] = min(ajustado[k], tope[k])
        # Reasigna el excedente por cocientes, saltando a quien ya está al tope.
        for valor, lista, div in cocientes(votos, n_escanos):
            if sobra == 0:
                break
            if div <= ajustado[lista] or ajustado[lista] >= tope[lista]:
                continue
            ajustado[lista] += 1
            sobra -= 1
        if sobra > 0:
            break  # nadie con sitio: el concejo queda incompleto, y es correcto
    return ajustado


def reparte_consejo_regional(votos: dict[str, int], n_escanos: int,
                             disponibles: dict[str, int] | None = None) -> Reparto:
    """Consejeros: sin premio a la mayoría. Con un escaño, gana el más votado.

    `disponibles` cuenta **solo titulares**: los accesitarios van en igual número
    que ellos y no se proclaman, así que no habilitan un escaño más.
    """
    votos = {k: v for k, v in votos.items() if v > 0}
    if not votos or n_escanos <= 0:
        return Reparto({}, None, False, False)
    desconocidas = (() if disponibles is None
                    else tuple(sorted(k for k in votos if k not in disponibles)))
    ganador, empate = _ganador(votos)
    if n_escanos == 1:
        gana = (ganador if disponibles is None
                or disponibles.get(ganador, 1) > 0 else None)
        esc = {k: (1 if k == gana else 0) for k in votos}
        return Reparto(esc, ganador, False, empate, 0, (),
                       tuple(k for k in desconocidas if esc.get(k, 0) > 0))
    escanos, pend, emp_l = dhondt(votos, n_escanos, disponibles)
    return Reparto(escanos, ganador, False, empate or bool(emp_l), pend, emp_l,
                   tuple(k for k in desconocidas if escanos.get(k, 0) > 0))


# ── Construcción de las entradas ─────────────────────────────────────────────
# Vive aquí y no en cada script porque el contrato de `disponibles` es la parte
# fácil de reimplementar mal: si se construye solo desde los candidatos hábiles,
# «lista sin nadie en pie» y «lista desconocida» colapsan en lo mismo, y eso
# rompe Aquía o rompe Pucará según cómo se interprete la ausencia.

def construye_disponibles(conocidas: set[str],
                          habiles: dict[str, int]) -> dict[str, int]:
    """Candidatos hábiles por lista, con **cero explícito** donde toca.

    `conocidas`: organizaciones con lista en el registro para esa carrera,
                 tengan o no candidatos en pie.
    `habiles`  : cuántos candidatos hábiles conserva cada una.

    Toda organización conocida aparece en el resultado, con 0 si se quedó sin
    nadie. Las que no están en `conocidas` quedan fuera a propósito: el
    allocator las trata como «no sabemos» y reparte sin topar.
    """
    return {org: habiles.get(org, 0) for org in conocidas}


def entradas_de_carrera(race_id: str, registro, inscritos) -> dict:
    """Arma `disponibles` y `promovidos` de una carrera desde los dos marcos.

    `registro` : el registro completo de candidaturas, con `race_id` y `id_jne`.
    `inscritos`: la salida de `candidatos_inscritos`, ya filtrada y con la regla
                 de promoción aplicada.

    Devuelve el diccionario listo para pasar a `reparte_concejo`.
    """
    conocidas = set(registro.loc[registro.race_id == race_id, "id_jne"])
    ins = inscritos[inscritos.race_id == race_id]
    regidores = ins[ins.cargo.str.startswith("REGIDOR")]
    habiles = regidores.groupby("id_jne").size().to_dict()
    promovidos = (ins[ins.origen_candidatura == "promocion_por_vacancia"]
                  .groupby("id_jne").size().to_dict())
    return {"disponibles": construye_disponibles(conocidas, habiles),
            "promovidos": promovidos}
