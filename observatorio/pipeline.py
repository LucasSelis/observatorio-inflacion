"""Pasos del pipeline como funciones simples; Dagster (definiciones.py) solo los orquesta."""
from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

import duckdb
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
    # Logs y artefactos de dbt van a una carpeta temporal: en un servidor el repo puede ser de solo lectura.
    temporal = tempfile.mkdtemp(prefix="dbt_")
    try:
        resultado = dbtRunner().invoke(["build", "--project-dir", str(DIR_DBT), "--profiles-dir", str(DIR_DBT),
                                        "--target-path", temporal, "--log-path", temporal])
    finally:
        _soltar_duckdb()
    if not resultado.success:
        raise RuntimeError(f"dbt build falló: {resultado.exception or 'hay tests o modelos con error'}")


def base_lista(ruta_db: str | Path) -> bool:
    """¿Existe la base con el mart y los resultados del backtest?"""
    if not Path(ruta_db).exists():
        return False
    try:
        con = carga.abrir_solo_lectura(ruta_db)
    except duckdb.Error:
        return False
    try:
        n = con.execute("select count(*) from information_schema.tables "
                        "where (table_schema, table_name) in (('marts', 'mart_mensual'), "
                        "('resultados', 'metricas'), ('resultados', 'pronostico_actual'))").fetchone()[0]
        return n == 3
    finally:
        con.close()


def asegurar_base(ruta_db: str | Path) -> None:
    """Si la base no está lista (primer arranque en un servidor), la arma desde el snapshot versionado."""
    if base_lista(ruta_db):
        return
    ingestar(ruta_db, "snapshot")  # idempotente: si la base existía a medias, solo completa lo que falta
    construir_modelos(ruta_db)
    backtest(ruta_db)


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
