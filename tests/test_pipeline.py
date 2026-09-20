"""Integracion: snapshot -> DuckDB -> dbt build -> backtest, sin red."""
from datetime import date

import duckdb
import pytest
from dagster import materialize

from observatorio import carga, pipeline
from observatorio.definiciones import Entorno, backtest, modelos_dbt, series_crudas


@pytest.fixture
def db(tmp_path):
    ruta = tmp_path / "test.duckdb"
    pipeline.ingestar(ruta, "snapshot")
    return ruta


def test_dbt_build_pasa_sobre_el_snapshot(db):
    pipeline.construir_modelos(db)
    # Regresion: dbt debe soltar el archivo, si no la app (otro proceso) no puede leerlo.
    con = duckdb.connect(str(db), read_only=True)
    n, sin_ipc = con.execute("select count(*), count(*) filter (where ipc_nivel is null) from marts.mart_mensual").fetchone()
    assert n > 100 and sin_ipc == 0


def _romper(db, sql):
    con = duckdb.connect(str(db))
    con.execute(sql)
    con.close()


def test_un_hueco_de_meses_en_el_ipc_corta_el_pipeline(db):
    _romper(db, "delete from raw.series_raw where serie='ipc' and fecha = date '2020-06-01'")
    with pytest.raises(RuntimeError, match="dbt build"):
        pipeline.construir_modelos(db)


def test_una_inflacion_absurda_corta_el_pipeline(db):
    _romper(db, "update raw.series_raw set valor = valor * 3 where serie='ipc' and fecha = date '2021-01-01'")
    with pytest.raises(RuntimeError, match="dbt build"):
        pipeline.construir_modelos(db)


def test_frescura_detecta_series_viejas(db):
    # El snapshot versionado llega hasta ago-2026: "hoy" se fija para que el test no dependa del reloj real.
    assert pipeline.problemas_de_frescura(db, hoy=date(2026, 9, 3)) == []
    viejos = pipeline.problemas_de_frescura(db, hoy=date(2027, 6, 1))
    assert any(p.startswith("ipc") for p in viejos) and any(p.startswith("dolar") for p in viejos)


def test_dagster_materializa_todo_de_punta_a_punta(tmp_path):
    ruta = tmp_path / "dagster.duckdb"
    r = materialize([series_crudas, modelos_dbt, backtest],
                    resources={"entorno": Entorno(ruta_db=str(ruta), fuente="snapshot",
                                                  dir_resultados=str(tmp_path / "resultados"))})
    assert r.success
    assert (tmp_path / "resultados" / "metricas.csv").exists()
    con = duckdb.connect(str(ruta), read_only=True)
    assert con.execute("select count(*) from resultados.metricas").fetchone()[0] > 0
    assert con.execute("select count(*) from resultados.pronostico_actual").fetchone()[0] == 1

