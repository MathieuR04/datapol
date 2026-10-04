"""Flujo A contra un servidor local. Respuestas sintéticas con los campos que lee
el 02a de EG 2026 (`totalActas`, `contabilizadas`, `totalVotosEmitidos`,
`codigoAgrupacionPolitica`, `totalVotosValidos`)."""

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

scrape_agregado = carga("02a_scrape_distritos")
from datapol.onpe import Cliente  # noqa: E402

RECURSO = "eleccion-municipal/participantes"


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    (tmp_path / "reference").mkdir()
    pd.DataFrame({"id_eleccion": [71, 72, 73, 74], "tipo": ["01", "02", "03", "04"]}
                 ).to_csv(tmp_path / "reference/id_eleccion.csv", index=False)
    pd.DataFrame({"race_id": ["01-010000", "03-010100", "04-010101"],
                  "tipo": ["01", "03", "04"],
                  "ubigeo": ["010000", "010100", "010101"],
                  "nivel_circunscripcion": ["departamento", "provincia", "distrito"]}
                 ).to_csv(tmp_path / "reference/carreras.csv", index=False)
    pedidas = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            pedidas.append((u.path, q))
            ide = int(q["idEleccion"])
            if ide == 74 and u.path.endswith(RECURSO):       # distrital: participantes caído
                self.send_response(500)
                self.end_headers()
                return
            if u.path.endswith("resumen-general/totales"):
                completa = ide == 71
                data = {"totalActas": 10, "contabilizadas": 10 if completa else 4,
                        "totalVotosEmitidos": 900}
            else:
                data = [{"codigoAgrupacionPolitica": 1, "nombreAgrupacionPolitica": "ORG 1",
                         "totalVotosValidos": 500},
                        {"codigoAgrupacionPolitica": 2, "nombreAgrupacionPolitica": "ORG 2",
                         "totalVotosValidos": 300},
                        {"codigoAgrupacionPolitica": 80, "totalVotosValidos": 60},
                        {"codigoAgrupacionPolitica": 81, "totalVotosValidos": 40}]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "data": data}).encode())

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(scrape_agregado, "Cliente",
                        partial(Cliente, delay=(0, 0), reintentos=2,
                                espera={"429": 0, "503": 0, "403": 0, "base": 0}))
    yield tmp_path, f"http://127.0.0.1:{srv.server_port}", pedidas
    srv.shutdown()


def corre(data, host, *extra):
    return scrape_agregado.main(["--host", host, "--recurso", RECURSO,
                                 "--data", str(data), "--workers", "2", *extra])


def test_ciclo_y_resueltas(entorno):
    data, host, pedidas = entorno
    assert corre(data, host) == 0
    tot = pd.concat(pd.read_parquet(f) for f in (data / "interim/agregado/totales").glob("*.parquet"))
    # la distrital no se escribe: le faltó una de sus dos respuestas
    assert sorted(tot.race_id) == ["01-010000", "03-010100"]
    g = tot.set_index("race_id").loc["01-010000"]
    assert (g.validos, g.blancos, g.nulos, g.actas_contabilizadas) == (800, 60, 40, 10)

    # los niveles de ubigeo: departamento sin provincia ni distrito
    q = next(q for p, q in pedidas if p.endswith("totales") and q["idEleccion"] == "71")
    assert q["tipoFiltro"] == "ubigeo_nivel_01" and q["idUbigeoDepartamento"] == "010000"
    assert "idUbigeoProvincia" not in q

    est = json.loads((data / "interim/agregado/estado.json").read_text())
    assert est == {"01-010000": "resuelta"}

    n = len(pedidas)
    assert corre(data, host) == 0
    # la gobernación ya resuelta no se pide más; las otras dos sí (2 peticiones c/u)
    nuevas = pedidas[n:]
    assert len(nuevas) >= 4 and all(q["idEleccion"] != "71" for _, q in nuevas)
    assert len(list((data / "interim/agregado/totales").glob("*.parquet"))) == 2
