"""Cliente del sistema en vivo de la ONPE (`presentacion-backend`).

Lo comparten los dos flujos de la noche:

    scripts/02b_scrape_mesas.py     flujo B, una petición por mesa
    scripts/02a_scrape_distritos.py  flujo A, totales por carrera

Tres cosas que no se negocian, todas de `shared/API-ONPE.md`:

1. **`curl_cffi` con impersonación de Chrome.** El WAF de CloudFront devuelve
   cuerpos vacíos a cualquier otro cliente.
2. **Sesión persistente por hilo**, no una por petición. Reusar la conexión TLS
   es la mitad del rendimiento.
3. **Nada pesado bajo el lock.** Comprimir o parsear dentro del mutex serializa a
   todos los workers. Bajo el lock solo se escribe.

SOBRE EL CRUDO
--------------
Toda respuesta con cuerpo se archiva **antes** de parsear (regla 4): una línea
JSON por respuesta, en archivos gzip que solo se crean, nunca se reabren. El
parseo se puede rehacer entero desde ahí sin volver a la red.

QUÉ NO SABEMOS HASTA QUE LA ONPE PUBLIQUE
-----------------------------------------
El host, el nombre del recurso de participantes por tipo de elección y el mapa
`idEleccion` → tipo. Los tres entran por línea de comandos o por
`data/reference/`, nunca escritos aquí.
"""

from __future__ import annotations

import gzip
import json
import os
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Contacto identificable (regla 11). El correo va por entorno y no en el código:
# este repo es público. `export DATAPOL_CONTACTO=correo@...` antes de correr.
USER_AGENT_CONTACTO = "datapol.lat (resultados ERM 2026; contacto: {})".format(
    os.environ.get("DATAPOL_CONTACTO", "https://datapol.lat"))

# Códigos reservados del detalle de votos. El 82 no existía en 2022.
COD_BLANCOS, COD_NULOS, COD_IMPUGNADOS = 80, 81, 82
CONTABILIZADA = "C"


def ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def nuevo_corte() -> str:
    """Id de corte. Con microsegundos: dos corridas en el mismo segundo
    compartían nombre y la segunda pisaba los archivos de la primera."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


# ------------------------------------------------------------------ red

@dataclass
class Cliente:
    """Una sesión por hilo y una política de reintentos común."""

    host: str                                   # https://resultados....onpe.gob.pe
    referer: str = "/main/actas"
    delay: tuple[float, float] = (0.02, 0.08)
    reintentos: int = 4
    timeout: float = 20
    # Esperas en segundos ante 429 / 503 / 403. Valores de API-ONPE.md.
    espera: dict = field(default_factory=lambda: {"429": 60, "503": 30, "403": 30, "base": 1})
    contadores: dict = field(default_factory=lambda: {
        "peticiones": 0, "200": 0, "204": 0, "429": 0, "503": 0,
        "403": 0, "vacio": 0, "error": 0})
    _local: threading.local = field(default_factory=threading.local)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _sesion(self):
        s = getattr(self._local, "s", None)
        if s is None:
            from curl_cffi import requests as cffi
            s = cffi.Session(impersonate="chrome124")
            s.headers.update({
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
                "Referer": self.host + self.referer,
                "Origin": self.host,
                # El impersonate fija el User-Agent de Chrome; el contacto va
                # aparte para no romper la huella que el WAF espera.
                "From": USER_AGENT_CONTACTO,
            })
            self._local.s = s
        return s

    def _cuenta(self, k: str) -> None:
        with self._lock:
            self.contadores[k] = self.contadores.get(k, 0) + 1

    def get(self, ruta: str, params: dict) -> tuple[int | None, str | None]:
        """-> (status, cuerpo). `(204, None)` es «no existe»; `(None, None)`,
        que se agotaron los reintentos. **Las dos son distintas**: lo primero se
        puede dar por resuelto, lo segundo nunca."""
        url = self.host + "/presentacion-backend/" + ruta.lstrip("/")
        for intento in range(self.reintentos):
            time.sleep(random.uniform(*self.delay))
            self._cuenta("peticiones")
            try:
                r = self._sesion().get(url, params=params, timeout=self.timeout)
            except Exception:
                self._cuenta("error")
                time.sleep(self.espera["base"] * 2 ** intento)
                continue
            st = r.status_code
            if st == 204:
                self._cuenta("204")
                return 204, None
            if st == 429:
                self._cuenta("429")
                time.sleep(self.espera["429"] * (intento + 1))
                continue
            if st == 503:
                self._cuenta("503")
                time.sleep(self.espera["503"])
                continue
            if st == 403:
                # El WAF responde 403 con una página HTML. Insistir rápido es
                # justo lo que lo mantiene cerrado.
                self._cuenta("403")
                time.sleep(self.espera["403"] * (intento + 1))
                continue
            if st != 200:
                self._cuenta("error")
                time.sleep(self.espera["base"] * 2 ** intento)
                continue
            cuerpo = r.text.strip()
            if not cuerpo:
                self._cuenta("vacio")
                time.sleep(self.espera["base"] * 2 ** intento)
                continue
            self._cuenta("200")
            return 200, cuerpo
        return None, None


# ------------------------------------------------------------------ crudo

class Crudo:
    """Archivo inmutable de respuestas: `{dir}/{corte}/{n:05d}.jsonl.gz`.

    Lo escribe **un solo hilo** (el principal), en el mismo momento en que se
    vuelcan las filas parseadas. Así el orden es siempre crudo → filas →
    checkpoint, y un proceso muerto a la mitad no deja filas sin su respuesta
    ni mesas marcadas como resueltas sin sus filas. Los workers solo hacen red.
    Nunca se reabre un archivo ya escrito.
    """

    def __init__(self, base: Path, corte: str):
        self.dir = base / corte
        self.dir.mkdir(parents=True, exist_ok=True)
        self._buf: list[str] = []
        self._n = len(list(self.dir.glob("*.jsonl.gz")))

    def guarda(self, ruta: str, params: dict, status: int, cuerpo: str | None) -> None:
        self._buf.append(json.dumps({"ts": ahora(), "ruta": ruta, "params": params,
                                     "status": status, "cuerpo": cuerpo},
                                    ensure_ascii=False))

    def vuelca(self) -> None:
        if not self._buf:
            return
        ruta = self.dir / f"{self._n:05d}.jsonl.gz"
        self._n += 1
        if ruta.exists():
            raise FileExistsError(f"crudo inmutable: {ruta} ya existe")
        tmp = ruta.with_suffix(".tmp")
        tmp.write_bytes(gzip.compress(("\n".join(self._buf) + "\n").encode()))
        tmp.replace(ruta)
        self._buf = []


def lee_crudo(base: Path):
    """Itera todas las respuestas archivadas, en orden de corte."""
    for f in sorted(base.glob("*/*.jsonl.gz")):
        with gzip.open(f, "rt") as fh:
            for linea in fh:
                if linea.strip():
                    yield json.loads(linea)


# ------------------------------------------------------------------ parseo

def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def actas_de(cuerpo: str) -> list[dict]:
    """El cuerpo de `/actas/buscar/mesa` -> lista de objetos acta."""
    d = json.loads(cuerpo)
    data = d.get("data") if isinstance(d, dict) else d
    if isinstance(data, dict):
        data = [data]
    return data or []


def parsea_acta(acta: dict, corte: str) -> tuple[dict | None, list[dict]]:
    """Un objeto acta -> (fila de acta, filas de voto). `(None, [])` = rechazada.

    GUARDA DE ATOMICIDAD: un acta `C` con emitidos > 0 y sin desglose se
    rechaza entera. Escribirla con ceros haría que el modo incremental la diera
    por cerrada y no la volviera a pedir nunca.
    """
    mesa = str(acta.get("codigoMesa") or "").zfill(6)
    if not mesa.strip("0"):
        return None, []
    estado = acta.get("codigoEstadoActa") or ""
    detalle = acta.get("detalle") or []
    emitidos = _int(acta.get("totalVotosEmitidos"))
    if estado == CONTABILIZADA and emitidos > 0 and not detalle:
        return None, []

    linea = acta.get("lineaTiempo") or []
    ts = sorted(_int(s.get("fechaRegistro")) for s in linea if s.get("fechaRegistro"))
    ts_c = [_int(s.get("fechaRegistro")) for s in linea
            if s.get("codigoEstadoActa") == CONTABILIZADA and s.get("fechaRegistro")]
    especiales = {COD_BLANCOS: 0, COD_NULOS: 0, COD_IMPUGNADOS: 0}
    votos = []
    for e in detalle:
        cod = _int(e.get("adAgrupacionPolitica"))
        v = _int(e.get("adVotos"))
        if cod in especiales:
            especiales[cod] = v
            continue
        votos.append({
            "corte": corte, "mesa": mesa, "id_eleccion": _int(acta.get("idEleccion")),
            "codigo_onpe": str(cod), "posicion_cedula": _int(e.get("adPosicion")),
            "agrupacion": (e.get("adDescripcion") or "").strip(), "votos": v,
        })
    fila = {
        "corte": corte, "mesa": mesa,
        "id_eleccion": _int(acta.get("idEleccion")),
        "ubigeo_distrito": str(acta.get("idUbigeo") or "").zfill(6),
        "codigo_local": str(acta.get("codigoLocalVotacion") or "").strip(),
        "nombre_local": str(acta.get("nombreLocalVotacion") or "").strip(),
        "electores": _int(acta.get("totalElectoresHabiles")),
        "emitidos": emitidos,
        "validos": _int(acta.get("totalVotosValidos")),
        "blancos": especiales[COD_BLANCOS],
        "nulos": especiales[COD_NULOS],
        "impugnados": especiales[COD_IMPUGNADOS],
        "estado_acta": estado,
        # Observada = pasó por cualquier estado que no es T/D/C en su historia.
        "ever_observada": any((s.get("codigoEstadoActa") or "") not in ("T", "D", "C")
                              for s in linea),
        "ts_primer_estado": ts[0] if ts else None,
        "ts_contabilizada": min(ts_c) if ts_c else None,
        "linea_tiempo": json.dumps(linea, ensure_ascii=False),
    }
    return fila, votos
