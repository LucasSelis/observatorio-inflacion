"""Catálogo de series y descarga desde la API de datos.gob.ar."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

API = "https://apis.datos.gob.ar/series/api/series/"
# La API responde 403 al User-Agent por defecto de urllib.
USER_AGENT = "observatorio-inflacion/1.0"


@dataclass(frozen=True)
class Serie:
    nombre: str
    id_api: str
    frecuencia: str  # "mensual" | "diaria"
    descripcion: str


SERIES: dict[str, Serie] = {
    s.nombre: s
    for s in (
        Serie("ipc", "148.3_INIVELNAL_DICI_M_26", "mensual", "IPC nacional, nivel general (dic-2016 = 100)"),
        Serie("salarios", "149.1_SOR_PRIADO_OCTU_0_25", "mensual", "Índice de salarios, empleo registrado privado"),
        Serie("emae", "143.3_NO_PR_2004_A_21", "mensual", "EMAE, actividad económica (2004 = 100)"),
        Serie("dolar", "168.1_T_CAMBIOR_D_0_0_26", "diaria", "Tipo de cambio BNA vendedor (pesos por dólar)"),
        Serie("reservas", "174.1_RRVAS_IDOS_0_0_36", "mensual", "Reservas internacionales del BCRA (millones de USD)"),
    )
}


def url_serie(id_api: str) -> str:
    return f"{API}?ids={id_api}&format=json&limit=5000&sort=asc"


def descargar(nombre: str, abrir=urllib.request.urlopen, reintentos: int = 3, espera: float = 1.5,
              dormir=time.sleep) -> list[tuple[str, float]]:
    """Devuelve [(fecha 'AAAA-MM-DD', valor)] sin los valores nulos. Reintenta ante errores de red o 5xx."""
    serie = SERIES[nombre]
    pedido = urllib.request.Request(url_serie(serie.id_api), headers={"User-Agent": USER_AGENT})
    ultimo_error: Exception | None = None
    for intento in range(1, reintentos + 1):
        try:
            with abrir(pedido, timeout=30) as respuesta:
                cuerpo = json.loads(respuesta.read().decode("utf-8"))
            filas = [(f, float(v)) for f, v in cuerpo["data"] if v is not None]
            if not filas:
                raise ValueError(f"La serie {nombre} llegó sin datos.")
            return filas
        except urllib.error.HTTPError as error:
            if 400 <= error.code < 500:
                raise  # un 4xx no se arregla reintentando
            ultimo_error = error
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            ultimo_error = error
        if intento < reintentos:
            dormir(espera * intento)
    raise RuntimeError(f"No se pudo descargar {nombre} tras {reintentos} intentos: {ultimo_error}")
