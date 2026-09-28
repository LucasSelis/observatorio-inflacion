"""Carga idempotente de las series crudas en DuckDB, con copia local para trabajar sin red."""
from __future__ import annotations

import csv
import os
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from . import fuentes

RAIZ = Path(__file__).resolve().parent.parent
RUTA_DB = Path(os.environ.get("OBS_DB", RAIZ / "observatorio.duckdb"))
DIR_SNAPSHOT = RAIZ / "datos" / "snapshot"


def conectar(ruta: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(ruta or RUTA_DB))
    asegurar_esquema(con)
    return con


def abrir_solo_lectura(ruta: str | Path) -> duckdb.DuckDBPyConnection:
    """Conexión para la app pública: solo lectura, sin acceso a archivos y con la configuración bloqueada.

    DuckDB comparte la instancia entre conexiones al mismo archivo dentro de un proceso y exige que la configuración
    coincida: por eso TODA lectura de la app pasa por esta función (si una leyera con otra config, fallaría al azar).
    """
    return duckdb.connect(str(ruta), read_only=True, config={
        "enable_external_access": False,
        "memory_limit": "512MB",
        "threads": 1,
        "lock_configuration": True,
    })


def asegurar_esquema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw.series_raw (
            serie      VARCHAR   NOT NULL,
            fecha      DATE      NOT NULL,
            valor      DOUBLE    NOT NULL,
            cargado_en TIMESTAMP NOT NULL,
            PRIMARY KEY (serie, fecha)
        )
        """
    )


def upsert(con: duckdb.DuckDBPyConnection, serie: str, filas: list[tuple[str, float]]) -> int:
    """Inserta o reemplaza por (serie, fecha): correr dos veces no duplica nada."""
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    con.executemany(
        "INSERT OR REPLACE INTO raw.series_raw VALUES (?, ?, ?, ?)",
        [(serie, date.fromisoformat(f), v, ahora) for f, v in filas],
    )
    return len(filas)


def cargar_desde_api(con: duckdb.DuckDBPyConnection, series: list[str] | None = None,
                     descargar=fuentes.descargar) -> dict[str, int]:
    return {n: upsert(con, n, descargar(n)) for n in (series or fuentes.SERIES)}


def guardar_snapshot(con: duckdb.DuckDBPyConnection, directorio: Path = DIR_SNAPSHOT) -> None:
    directorio.mkdir(parents=True, exist_ok=True)
    for nombre in fuentes.SERIES:
        filas = con.execute(
            "SELECT strftime(fecha, '%Y-%m-%d'), valor FROM raw.series_raw WHERE serie = ? ORDER BY fecha", [nombre]
        ).fetchall()
        with open(directorio / f"{nombre}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["fecha", "valor"])
            w.writerows((fecha, repr(valor)) for fecha, valor in filas)


def cargar_desde_snapshot(con: duckdb.DuckDBPyConnection, directorio: Path = DIR_SNAPSHOT) -> dict[str, int]:
    resultado = {}
    for nombre in fuentes.SERIES:
        with open(directorio / f"{nombre}.csv", newline="", encoding="utf-8") as f:
            filas = [(r["fecha"], float(r["valor"])) for r in csv.DictReader(f)]
        resultado[nombre] = upsert(con, nombre, filas)
    return resultado


def frescura(con: duckdb.DuckDBPyConnection):
    """Última fecha y cantidad de filas por serie."""
    return con.execute(
        "SELECT serie, max(fecha) AS ultima_fecha, count(*) AS filas FROM raw.series_raw GROUP BY serie ORDER BY serie"
    ).df()
