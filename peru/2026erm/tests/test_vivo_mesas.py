"""Flujo B de punta a punta contra un servidor local que imita a la ONPE.

Las respuestas son **sintéticas**: se arman con los campos documentados en
`shared/API-ONPE.md` y los que lee el 02b de EG 2026 (`codigoMesa`, `idUbigeo`,
`idEleccion`, `codigoEstadoActa`, `lineaTiempo`, `detalle[].adAgrupacionPolitica`
…). El 4 de octubre la ONPE devolvió 403 al sitio histórico de EG 2026, así que
no hubo respuestas reales que archivar como fixture. Cuando haya crudo de ERM
2026 en `data/raw/onpe_vivo/`, conviene sumar un caso con una respuesta real.
"""

from __future__ import annotations

import json
import sys
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "scripts"))

from _scripts import carga  # noqa: E402

consolida = carga("03_consolida_mesas")
scrape_mesas = carga("02b_scrape_mesas")
from datapol import onpe  # noqa: E402
from datapol.onpe import Cliente, lee_crudo, parsea_acta  # noqa: E402

# idEleccion inventados a propósito: el código no puede depender de ellos.
GOB, CONS, PROV, DIST = 71, 72, 73, 74


def acta(mesa, ide, estado="C", votos=((1, 50), (2, 30)), blancos=5, nulos=3,
         impugnados=0, ubigeo="010101", sin_detalle=False, observada=False):
    linea = [{"codigoEstadoActa": "T", "fechaRegistro": 1_000},
             {"codigoEstadoActa": "D", "fechaRegistro": 2_000}]
    if observada:
        linea.append({"codigoEstadoActa": "E", "fechaRegistro": 2_500})
    if estado == "C":
        linea.append({"codigoEstadoActa": "C", "fechaRegistro": 3_000})
    det = [] if sin_detalle else (
        [{"adAgrupacionPolitica": c, "adPosicion": c, "adDescripcion": f"ORG {c}",
          "adVotos": v} for c, v in votos]
        + [{"adAgrupacionPolitica": 80, "adVotos": blancos},
           {"adAgrupacionPolitica": 81, "adVotos": nulos},
           {"adAgrupacionPolitica": 82, "adVotos": impugnados}])
    val = sum(v for _, v in votos)
    return {"codigoMesa": mesa, "idEleccion": ide, "idUbigeo": ubigeo,
            "codigoEstadoActa": estado, "codigoLocalVotacion": "0001",
            "nombreLocalVotacion": "IE PRUEBA", "totalElectoresHabiles": 300,
            "totalVotosEmitidos": val + blancos + nulos + impugnados,
            "totalVotosValidos": val, "lineaTiempo": linea, "detalle": det}


class Onpe:
    """Estado del servidor falso: qué responde cada mesa y cuántas veces."""

    def __init__(self):
        self.respuestas: dict[str, list] = {}   # mesa -> cola de (status, cuerpo)
        self.pedidas: dict[str, int] = {}
        self.lock = threading.Lock()

    def fija(self, mesa, *respuestas):
        self.respuestas[mesa] = list(respuestas)

    def responde(self, mesa):
        with self.lock:
            self.pedidas[mesa] = self.pedidas.get(mesa, 0) + 1
            cola = self.respuestas.get(mesa, [(204, None)])
            return cola.pop(0) if len(cola) > 1 else cola[0]


def ok(*actas):
    return (200, json.dumps({"success": True, "data": list(actas)}))


@pytest.fixture
def servidor():
    estado = Onpe()

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            assert u.path == "/presentacion-backend/actas/buscar/mesa"
            mesa = parse_qs(u.query)["codigoMesa"][0]
            st, cuerpo = estado.responde(mesa)
            self.send_response(st)
            self.end_headers()
            if cuerpo is not None:
                self.wfile.write(cuerpo.encode())

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield estado, f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture
def data(tmp_path, monkeypatch):
    (tmp_path / "processed").mkdir()
    (tmp_path / "reference").mkdir()
    # 000004 es de cercado: no elige alcalde distrital.
    pd.DataFrame({
        "mesa": ["000001", "000002", "000003", "000004"],
        "ubigeo_distrito": ["010101", "010101", "010102", "010101"],
        "race_gobernador": ["01-010000"] * 4,
        "race_consejero": ["02-010100"] * 4,
        "race_provincial": ["03-010100"] * 4,
        "race_distrital": ["04-010101", "04-010101", "04-010102", ""],
    }).to_parquet(tmp_path / "processed/mesas.parquet")
    rapido = partial(Cliente, delay=(0, 0), reintentos=3,
                     espera={"429": 0, "503": 0, "403": 0, "base": 0})
    monkeypatch.setattr(scrape_mesas, "Cliente", rapido)
    return tmp_path


def corre(data, host, *extra):
    return scrape_mesas.main(["--host", host, "--data", str(data), "--workers", "3", *extra])


def cuatro(mesa, **kw):
    return [acta(mesa, i, **kw) for i in (GOB, CONS, PROV, DIST)]


def test_barrido_reintentos_y_guarda(servidor, data):
    onpe_, host = servidor
    onpe_.fija("000001", (503, None), ok(*cuatro("000001")))           # 503 y luego bien
    onpe_.fija("000002", (200, ""), ok(*cuatro("000002", estado="D")))  # vacío y luego pendiente
    # 000003: un acta C sin desglose -> la guarda la rechaza, la mesa queda pendiente
    onpe_.fija("000003", ok(acta("000003", GOB, ubigeo="010102"),
                            acta("000003", DIST, ubigeo="010102", sin_detalle=True)))
    onpe_.fija("000004", ok(*[acta("000004", i) for i in (GOB, CONS, PROV)]))

    assert corre(data, host) == 0
    est = json.loads((data / "interim/mesas/estado.json").read_text())
    assert est == {"000001": "resuelta", "000002": "pendiente",
                   "000003": "pendiente", "000004": "resuelta"}

    actas = pd.concat(pd.read_parquet(f) for f in (data / "interim/mesas/actas").glob("*.parquet"))
    # 4 + 4 + 1 (la rechazada no se escribe) + 3
    assert len(actas) == 12
    assert not ((actas.mesa == "000003") & (actas.id_eleccion == DIST)).any()
    fila = actas[(actas.mesa == "000001") & (actas.id_eleccion == GOB)].iloc[0]
    assert (fila.blancos, fila.nulos, fila.impugnados, fila.validos) == (5, 3, 0, 80)
    assert fila.ts_contabilizada == 3_000

    # el crudo tiene una línea por respuesta con cuerpo útil o 204
    crudo = list(lee_crudo(data / "raw/onpe_vivo/mesas"))
    assert sorted(r["params"]["codigoMesa"] for r in crudo) == ["000001", "000002", "000003", "000004"]


def test_incremental_no_repite_resueltas(servidor, data):
    onpe_, host = servidor
    for m in ("000001", "000004"):
        onpe_.fija(m, ok(*cuatro(m)))
    onpe_.fija("000002", ok(*cuatro("000002", estado="D")), ok(*cuatro("000002")))
    onpe_.fija("000003", (204, None))
    assert corre(data, host) == 0
    antes = dict(onpe_.pedidas)

    # Sin --update no se pide nada: todo está en el checkpoint.
    assert corre(data, host) == 0
    assert onpe_.pedidas == antes

    # Con --update solo la pendiente.
    assert corre(data, host, "--update") == 0
    nuevas = {m: n - antes.get(m, 0) for m, n in onpe_.pedidas.items() if n != antes.get(m, 0)}
    assert nuevas == {"000002": 1}
    est = json.loads((data / "interim/mesas/estado.json").read_text())
    assert est["000002"] == "resuelta" and est["000003"] == "inexistente"


def test_fallida_no_se_marca(servidor, data):
    onpe_, host = servidor
    for m in ("000001", "000002", "000003"):
        onpe_.fija(m, ok(*cuatro(m)))
    onpe_.fija("000004", (500, None))         # agota los reintentos
    assert corre(data, host) == 0
    est = json.loads((data / "interim/mesas/estado.json").read_text())
    assert "000004" not in est
    onpe_.fija("000004", ok(*[acta("000004", i) for i in (GOB, CONS, PROV)]))
    assert corre(data, host) == 0
    est = json.loads((data / "interim/mesas/estado.json").read_text())
    assert est["000004"] == "resuelta"


def test_interrupcion_reanuda_sin_perder_ni_repetir(servidor, data, monkeypatch):
    """Muere tras el primer volcado: lo volcado no se repide, lo demás sí."""
    onpe_, host = servidor
    for m in ("000001", "000002", "000003", "000004"):
        onpe_.fija(m, ok(*cuatro(m)))
    monkeypatch.setattr(scrape_mesas, "VOLCAR_CADA", 2)
    real = scrape_mesas.Volcador.vuelca
    llamadas = {"n": 0}

    def muere(self):
        real(self)
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(scrape_mesas.Volcador, "vuelca", muere)
    with pytest.raises(KeyboardInterrupt):
        corre(data, host, "--workers", "1")
    est = json.loads((data / "interim/mesas/estado.json").read_text())
    assert len(est) == 2
    primeras = set(est)

    monkeypatch.setattr(scrape_mesas.Volcador, "vuelca", real)
    pedidas_antes = dict(onpe_.pedidas)
    assert corre(data, host) == 0
    est = json.loads((data / "interim/mesas/estado.json").read_text())
    assert len(est) == 4
    for m in primeras:                         # no se repidieron
        assert onpe_.pedidas[m] == pedidas_antes[m]
    # y las filas de cada mesa están exactamente una vez por corte
    actas = pd.concat(pd.read_parquet(f) for f in (data / "interim/mesas/actas").glob("*.parquet"))
    assert not actas.duplicated(["corte", "mesa", "id_eleccion"]).any()
    assert set(actas.mesa) == {"000001", "000002", "000003", "000004"}


def test_consolida_descubre_y_luego_publica(servidor, data):
    onpe_, host = servidor
    onpe_.fija("000001", ok(*cuatro("000001", estado="D", observada=True)), ok(*cuatro("000001")))
    onpe_.fija("000002", ok(*cuatro("000002")))
    onpe_.fija("000003", ok(*cuatro("000003", ubigeo="010102")))
    onpe_.fija("000004", ok(*[acta("000004", i) for i in (GOB, CONS, PROV)]))
    corre(data, host)
    docs = data / "docs"
    assert consolida.main(["--data", str(data), "--docs", str(docs)]) == 2
    rep = (docs / "id_eleccion_descubrimiento.md").read_text()
    assert f"| {DIST} | 3 | 0 | 04 (no aparece en cercados) |" in rep

    pd.DataFrame({"id_eleccion": [GOB, CONS, PROV, DIST],
                  "tipo": ["01", "02", "03", "04"]}).to_csv(
        data / "reference/id_eleccion.csv", index=False)
    corre(data, host, "--update")             # 000001 pasa a C limpia; fue observada en el corte anterior
    assert consolida.main(["--data", str(data), "--docs", str(docs)]) == 0

    comp = pd.read_parquet(data / "processed/computo_mesa_ERM2026.parquet")
    res = pd.read_parquet(data / "processed/resultados_mesa_ERM2026.parquet")
    # el esquema que lee `carga_todo` de 2022
    for c in ["mesa", "tipo", "ubigeo_distrito", "local", "electores", "votaron",
              "observacion", "votos_validos", "votos_blancos", "votos_nulos",
              "votos_impugnados"]:
        assert c in comp.columns
    for c in ["mesa", "tipo", "ubigeo_distrito", "codigo_onpe", "agrupacion", "votos"]:
        assert c in res.columns
    assert len(comp) == 15 and (comp.observacion == "CONTABILIZADAS NORMALES").all()
    m1 = comp[(comp.mesa == 1) & (comp.tipo == "01")].iloc[0]
    assert m1.ever_observada and m1.race_id == "01-010000"
    assert comp[(comp.mesa == 3) & (comp.tipo == "04")].race_id.iloc[0] == "04-010102"
    assert res.groupby(["mesa", "tipo"]).votos.sum().eq(80).all()


def test_ever_observada_es_monotona():
    """Si un corte la vio observada, el siguiente en C no la limpia."""
    f1, _ = parsea_acta(acta("000001", GOB, estado="D", observada=True), "c1")
    f2, _ = parsea_acta(acta("000001", GOB), "c2")
    assert f1["ever_observada"] and not f2["ever_observada"]
    # la monotonía la impone consolida (bool_or sobre los cortes): ver test anterior


def test_respuesta_sin_data_es_lista_vacia():
    assert onpe.actas_de(json.dumps({"success": True, "data": None})) == []
