"""Ejecución segura de SQL escrito por un visitante (explorador SQL de la app).

Capas de defensa, de la más fuerte a la más débil:
1. Base abierta en solo lectura y sin acceso externo (`carga.abrir_solo_lectura`): no puede escribir la base
   ni leer/escribir archivos, ni cargar extensiones, ni cambiar esa configuración.
2. Solo una sentencia y solo de tipo SELECT (incluye WITH y FROM-first). Sin PRAGMA, COPY, ATTACH, INSTALL, etc.
3. Límite de filas devueltas, límite de memoria y tiempo máximo (se interrumpe la consulta).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import duckdb
import pandas as pd

from . import carga

MAX_FILAS = 1000
TIMEOUT_S = 10.0


class ConsultaRechazada(ValueError):
    """La consulta no es una sola sentencia SELECT, o falló al ejecutarse; el mensaje es apto para mostrar."""


@dataclass(frozen=True)
class Resultado:
    tabla: pd.DataFrame
    truncado: bool  # hay más filas que MAX_FILAS


def validar(sql: str) -> str:
    """Devuelve la consulta limpia o levanta ConsultaRechazada."""
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise ConsultaRechazada("Escribí una consulta.")
    try:
        sentencias = duckdb.extract_statements(sql)
    except duckdb.Error as error:
        raise ConsultaRechazada(f"No pude interpretar la consulta: {_limpio(error)}") from None
    if len(sentencias) != 1:
        raise ConsultaRechazada("Solo se permite una consulta por vez.")
    if sentencias[0].type != duckdb.StatementType.SELECT:
        raise ConsultaRechazada("Solo se permiten consultas SELECT (con WITH, JOIN, funciones de ventana, etc.).")
    return sql


def ejecutar(ruta_db, sql: str, max_filas: int = MAX_FILAS, timeout_s: float = TIMEOUT_S) -> Resultado:
    sql = validar(sql)
    con = carga.abrir_solo_lectura(ruta_db)
    reloj = threading.Timer(timeout_s, con.interrupt)
    reloj.start()
    try:
        # El salto de línea antes de ")" evita que un comentario "--" final se coma el paréntesis.
        tabla = con.execute(f"SELECT * FROM (\n{sql}\n) AS consulta LIMIT {max_filas + 1}").df()
    except duckdb.InterruptException:
        raise ConsultaRechazada(f"La consulta tardó más de {timeout_s:g} segundos y se canceló.") from None
    except duckdb.Error as error:
        raise ConsultaRechazada(_limpio(error)) from None
    finally:
        reloj.cancel()
        con.close()
    return Resultado(tabla.head(max_filas), truncado=len(tabla) > max_filas)


def tablas_disponibles(ruta_db) -> pd.DataFrame:
    """Esquema.tabla y columnas de lo que se puede consultar."""
    con = carga.abrir_solo_lectura(ruta_db)
    try:
        return con.execute(
            """
            select table_schema || '.' || table_name as tabla,
                   string_agg(column_name || ' (' || lower(data_type) || ')', ', ' order by ordinal_position) as columnas
            from information_schema.columns
            where table_schema in ('marts', 'staging', 'resultados', 'raw')
            group by table_schema, table_name
            order by table_schema, table_name
            """
        ).df()
    finally:
        con.close()


def _limpio(error: Exception) -> str:
    """Primera línea del error de DuckDB, sin rutas ni detalles internos."""
    return str(error).splitlines()[0][:300]


EJEMPLOS: dict[str, str] = {
    "Inflación promedio y máxima por año": """\
SELECT year(mes) AS anio,
       round(avg(inflacion_m), 2) AS promedio_mensual,
       round(max(inflacion_m), 2) AS maximo_mensual
FROM marts.mart_mensual
WHERE inflacion_m IS NOT NULL
GROUP BY 1
ORDER BY 1""",
    "Los 10 meses con más inflación (RANK)": """\
SELECT rank() OVER (ORDER BY inflacion_m DESC) AS puesto,
       strftime(mes, '%Y-%m') AS mes,
       round(inflacion_m, 1) AS inflacion_pct,
       round(dolar_var_m, 1) AS dolar_var_pct
FROM marts.mart_mensual
WHERE inflacion_m IS NOT NULL
QUALIFY puesto <= 10
ORDER BY puesto""",
    "Promedio móvil de 12 meses": """\
SELECT strftime(mes, '%Y-%m') AS mes,
       round(inflacion_m, 2) AS inflacion_pct,
       round(avg(inflacion_m) OVER (ORDER BY mes ROWS BETWEEN 11 PRECEDING AND CURRENT ROW), 2) AS promedio_12m
FROM marts.mart_mensual
WHERE inflacion_m IS NOT NULL
ORDER BY mes DESC
LIMIT 24""",
    "Aceleración de la inflación (LAG)": """\
WITH base AS (
    SELECT mes, inflacion_m,
           lag(inflacion_m) OVER (ORDER BY mes) AS mes_anterior
    FROM marts.mart_mensual
)
SELECT strftime(mes, '%Y-%m') AS mes,
       round(inflacion_m, 2) AS inflacion_pct,
       round(inflacion_m - mes_anterior, 2) AS cambio_pp
FROM base
WHERE mes_anterior IS NOT NULL
ORDER BY abs(inflacion_m - mes_anterior) DESC
LIMIT 10""",
    "Error de cada modelo por año (backtest)": """\
SELECT year(mes_objetivo) AS anio,
       count(*) AS meses,
       round(avg(abs(naive - real)), 2) AS error_ingenuo,
       round(avg(abs(ar2 - real)), 2) AS error_ar2,
       round(avg(abs(arx_dolar - real)), 2) AS error_ar_dolar
FROM resultados.predicciones
GROUP BY 1
ORDER BY 1""",
    "¿Cuánto valen hoy $100.000 de enero de 2017?": """\
WITH ultimo AS (
    SELECT ipc_nivel FROM marts.mart_mensual ORDER BY mes DESC LIMIT 1
)
SELECT strftime(m.mes, '%Y-%m') AS desde,
       100000 AS pesos_de_entonces,
       round(100000 * u.ipc_nivel / m.ipc_nivel) AS pesos_de_hoy
FROM marts.mart_mensual AS m, ultimo AS u
WHERE m.mes = DATE '2017-01-01'""",
    "Meses en que el dólar subió más de 5% (y qué pasó después)": """\
SELECT strftime(mes, '%Y-%m') AS mes,
       round(dolar_var_m, 1) AS dolar_var_pct,
       round(inflacion_m, 1) AS inflacion_pct,
       round(lead(inflacion_m) OVER (ORDER BY mes), 1) AS inflacion_mes_siguiente
FROM marts.mart_mensual
QUALIFY dolar_var_m > 5
ORDER BY mes""",
}
