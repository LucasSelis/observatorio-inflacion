from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from observatorio import pipeline

RUTA_APP = str(Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py")


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    ruta = tmp_path_factory.mktemp("app") / "app.duckdb"
    pipeline.ingestar(ruta, "snapshot")
    pipeline.construir_modelos(ruta)
    pipeline.backtest(ruta)
    return ruta


def test_la_app_renderiza_sin_excepciones(base, monkeypatch):
    monkeypatch.setenv("OBS_DB", str(base))
    at = AppTest.from_file(RUTA_APP, default_timeout=60).run()
    assert not at.exception
    assert "anticipar la inflación" in at.title[0].value


def test_cambiar_de_periodo_no_rompe(base, monkeypatch):
    monkeypatch.setenv("OBS_DB", str(base))
    at = AppTest.from_file(RUTA_APP, default_timeout=60).run()
    at.radio[0].set_value("desde_2024").run()
    assert not at.exception


def test_sin_base_muestra_un_error_claro(tmp_path, monkeypatch):
    monkeypatch.setenv("OBS_DB", str(tmp_path / "no_existe.duckdb"))
    at = AppTest.from_file(RUTA_APP, default_timeout=60).run()
    assert at.error and "No encontré la base" in at.error[0].value
