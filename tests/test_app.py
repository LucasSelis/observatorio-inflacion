from pathlib import Path

from streamlit.testing.v1 import AppTest

from observatorio import consultas

RAIZ = Path(__file__).resolve().parent.parent
RUTA_APP = str(RAIZ / "app" / "Observatorio.py")
RUTA_SQL = str(RAIZ / "app" / "pages" / "1_Explorador_SQL.py")


def test_la_app_renderiza_sin_excepciones(base_lista, monkeypatch):
    monkeypatch.setenv("OBS_DB", str(base_lista))
    at = AppTest.from_file(RUTA_APP, default_timeout=90).run()
    assert not at.exception
    assert "anticipar la inflación" in at.title[0].value


def test_cambiar_de_periodo_no_rompe(base_lista, monkeypatch):
    monkeypatch.setenv("OBS_DB", str(base_lista))
    at = AppTest.from_file(RUTA_APP, default_timeout=90).run()
    at.radio[0].set_value("desde_2024").run()
    assert not at.exception


def test_sin_base_la_app_la_arma_sola_desde_el_snapshot(tmp_path, monkeypatch):
    """En un servidor no existe mi archivo DuckDB: el primer arranque debe construirlo."""
    monkeypatch.setenv("OBS_DB", str(tmp_path / "no_existe.duckdb"))
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    at = AppTest.from_file(RUTA_APP, default_timeout=180).run()
    assert not at.exception
    assert (tmp_path / "observatorio_app.duckdb").exists()


def test_el_explorador_sql_corre_el_primer_ejemplo(base_lista, monkeypatch):
    monkeypatch.setenv("OBS_DB", str(base_lista))
    at = AppTest.from_file(RUTA_SQL, default_timeout=90).run()
    assert not at.exception and not at.error
    assert len(at.dataframe) >= 1


def test_el_explorador_muestra_error_claro_ante_un_drop(base_lista, monkeypatch):
    monkeypatch.setenv("OBS_DB", str(base_lista))
    at = AppTest.from_file(RUTA_SQL, default_timeout=90).run()
    at.text_area(key="sql").set_value("DROP TABLE marts.mart_mensual")
    at.button[0].click().run()
    assert not at.exception
    assert at.error and "SELECT" in at.error[0].value


def test_el_explorador_cambia_de_ejemplo(base_lista, monkeypatch):
    monkeypatch.setenv("OBS_DB", str(base_lista))
    at = AppTest.from_file(RUTA_SQL, default_timeout=90).run()
    segundo = list(consultas.EJEMPLOS)[1]
    at.selectbox[0].set_value(segundo).run()
    assert not at.exception and not at.error
    assert at.text_area(key="sql").value == consultas.EJEMPLOS[segundo]
