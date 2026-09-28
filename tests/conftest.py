import pytest

from observatorio import pipeline


@pytest.fixture(scope="session")
def base_lista(tmp_path_factory):
    """Base completa (snapshot -> dbt -> backtest) armada una sola vez para toda la sesión de tests."""
    ruta = tmp_path_factory.mktemp("base") / "sesion.duckdb"
    pipeline.asegurar_base(ruta)
    return ruta
