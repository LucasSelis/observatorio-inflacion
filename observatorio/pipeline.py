"""Pasos del pipeline como funciones simples; Dagster (definiciones.py) solo los orquesta."""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

from dbt.adapters.duckdb.connections import DuckDBConnectionManager
from dbt.adapters.factory import cleanup_connections
from dbt.cli.main import dbtRunner

from . import carga, pronostico

DIR_DBT = carga.RAIZ / "dbt"


def ingestar(ruta_db: str | Path, fuente: str = "api") -> dict[str, int]:
    """fuente='api' baja de datos.gob.ar y refresca el snapshot; 'snapshot' usa la copia versionada (CI, offline)."""
    con = carga.conectar(ruta_db)
    try:
        if fuente == "api":
            filas = carga.cargar_desde_api(con)
            carga.guardar_snapshot(con)
        elif fuente == "snapshot":
            filas = carga.cargar_desde_snapshot(con)
        else:
            raise ValueError(f"fuente desconocida: {fuente!r}")
        return filas
    finally:
        con.close()


def _soltar_duckdb() -> None:
    """dbt-duckdb mantiene una conexión de clase abierta y `cleanup_connections` solo la des-referencia sin cerrarla:
    el archivo queda bloqueado para otros procesos (la app de Streamlit) mientras viva este proceso (p. ej. Dagster).
    Se cierra a mano; `_ENV` es interno de dbt-duckdb, por eso está cubierto por un test de regresión."""
    cleanup_connections()
    entorno = getattr(DuckDBConnectionManager, "_ENV", None)
    if entorno is not None:
        entorno.close()
        DuckDBConnectionManager._ENV = None


def construir_modelos(ruta_db: str | Path) -> None:
    """Corre `dbt build` (modelos + tests). Si algún test falla, levanta excepción y el pipeline se corta."""
    os.environ["OBS_DB"] = str(ruta_db)
    try:
        resultado = dbtRunner().invoke(["build", "--project-dir", str(DIR_DBT), "--profiles-dir", str(DIR_DBT)])
    finally:
        _soltar_duckdb()
    if not resultado.success:
        raise RuntimeError(f"dbt build falló: {resultado.exception or 'hay tests o modelos con error'}")


def backtest(ruta_db: str | Path, dir_resultados: str | Path | None = None) -> dict:
    """Corre el backtest; si se indica `dir_resultados`, además deja los resultados como CSV legibles sin DuckDB."""
    con = carga.conectar(ruta_db)
    try:
        resultado = pronostico.ejecutar(con)
    finally:
        con.close()
    if dir_resultados:
        destino = Path(dir_resultados)
        destino.mkdir(parents=True, exist_ok=True)
        for nombre, df in resultado.items():
            df.to_csv(destino / f"{nombre}.csv", index=False, float_format="%.4f")
    return resultado


def problemas_de_frescura(ruta_db: str | Path, hoy: date | None = None) -> list[str]:
    """Devuelve la lista de series demasiado viejas.

    IPC sale ~45 días después del mes. El dólar es diario, pero datos.gob.ar lo actualiza con ~3 semanas de demora
    (se midió en sept-2026: último dato 31-ago); con 7 días la alerta estaría siempre encendida y no serviría.
    """
    hoy = hoy or date.today()
    maximos = {"ipc": 75, "dolar": 35}
    con = carga.conectar(ruta_db)
    try:
        ultimas = {s: f for s, f in con.execute("select serie, max(fecha) from raw.series_raw group by 1").fetchall()}
    finally:
        con.close()
    problemas = []
    for serie, dias in maximos.items():
        if serie not in ultimas:
            problemas.append(f"{serie}: sin datos")
        elif ultimas[serie] < hoy - timedelta(days=dias):
            problemas.append(f"{serie}: último dato {ultimas[serie]} (más de {dias} días)")
    return problemas
