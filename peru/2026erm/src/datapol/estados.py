"""Vocabulario de estados de una proyección. Contrato con el frontend.

Toda autoridad de las 2,116 carreras está siempre en uno de cinco estados. El
primero es la base —de donde salen todas— y los otros cuatro son terminales:
afirmaciones verificables que el producto publica y que, si cambian, cuentan
como retractación.

    POR_DEFINIR    la proyección todavía no alcanza el nivel de confianza
                   exigido. Es el estado inicial y el único no publicable como
                   resultado.

    ELECTO         hay un ganador con nombre: el ejecutivo, o un escaño del
                   cuerpo proporcional ya adjudicado a una lista.

    SEGUNDA_VUELTA solo gobernador. Nadie alcanza el 30% de los votos válidos y
                   pasan las dos primeras listas. El pronóstico nombra a las dos.

    EMPATE         empate exacto de votos entre las listas que se disputan el
                   puesto o el escaño. La ley lo resuelve **por sorteo**, así que
                   declarar el empate es el pronóstico correcto; inventar un
                   ganador sería peor.

    SIN_RESULTADO  no hay autoridad que elegir porque no hay votos válidos: en
                   ERM 2022, Recta, Manitea y Huamantanga tuvieron **todas** sus
                   actas anuladas. No es un dato faltante, es el resultado.

`POR_DEFINIR` nunca se cuenta como llamada. Los otros cuatro sí, y los cuatro se
juzgan igual contra el resultado final.
"""

from __future__ import annotations

POR_DEFINIR = "por_definir"
ELECTO = "electo"
SEGUNDA_VUELTA = "segunda_vuelta"
EMPATE = "empate"
SIN_RESULTADO = "sin_resultado"

TERMINALES = (ELECTO, SEGUNDA_VUELTA, EMPATE, SIN_RESULTADO)
TODOS = (POR_DEFINIR,) + TERMINALES


def es_llamada(estado: str) -> bool:
    """Un estado terminal es una afirmación publicable, y por tanto retractable."""
    return estado in TERMINALES


def formatea(estado: str, quienes: tuple[str, ...] = ()) -> str:
    """Representación plana para las tablas: `estado|org[|org…]`."""
    return "|".join((estado,) + tuple(quienes))
