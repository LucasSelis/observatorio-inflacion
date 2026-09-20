"""Dagster: series_crudas -> modelos_dbt -> backtest, con chequeo de frescura y corrida diaria."""
from __future__ import annotations

import os

from dagster import (AssetCheckResult, AssetSelection, ConfigurableResource, Definitions, ScheduleDefinition,
                     asset, asset_check, define_asset_job)

from . import carga, pipeline


class Entorno(ConfigurableResource):
    ruta_db: str = str(carga.RUTA_DB)
    fuente: str = "api"  # "api" | "snapshot"
    dir_resultados: str = str(carga.RAIZ / "resultados")  # CSV versionados; "" para no exportar


@asset(group_name="ingesta", description="Series crudas de datos.gob.ar en DuckDB (carga idempotente).")
def series_crudas(entorno: Entorno) -> None:
    pipeline.ingestar(entorno.ruta_db, entorno.fuente)


@asset(deps=[series_crudas], group_name="modelado",
       description="Modelos dbt (staging + mart_mensual) con sus tests; si un test falla, no sigue.")
def modelos_dbt(entorno: Entorno) -> None:
    pipeline.construir_modelos(entorno.ruta_db)


@asset(deps=[modelos_dbt], group_name="pronostico",
       description="Backtest con ventana expansiva, métricas, bootstrap y pronóstico del mes próximo.")
def backtest(entorno: Entorno) -> None:
    pipeline.backtest(entorno.ruta_db, entorno.dir_resultados or None)


@asset_check(asset=series_crudas, description="IPC con menos de 75 días y dólar con menos de 35.")
def frescura_de_series(entorno: Entorno) -> AssetCheckResult:
    problemas = pipeline.problemas_de_frescura(entorno.ruta_db)
    return AssetCheckResult(passed=not problemas, metadata={"problemas": ", ".join(problemas) or "ninguno"})


corrida_diaria = ScheduleDefinition(
    job=define_asset_job("actualizar_todo", selection=AssetSelection.all()),
    cron_schedule="0 9 * * *",
    execution_timezone="America/Argentina/Buenos_Aires",
)

defs = Definitions(
    assets=[series_crudas, modelos_dbt, backtest],
    asset_checks=[frescura_de_series],
    schedules=[corrida_diaria],
    resources={"entorno": Entorno(ruta_db=os.environ.get("OBS_DB", str(carga.RUTA_DB)),
                                  fuente=os.environ.get("OBS_FUENTE", "api"))},
)
