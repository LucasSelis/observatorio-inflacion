import io
import json
import urllib.error

import pytest

from observatorio import carga, fuentes


class Respuesta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def respuesta(datos):
    return Respuesta(json.dumps({"data": datos}).encode("utf-8"))


def error_http(codigo):
    return urllib.error.HTTPError("http://x", codigo, "err", {}, None)


def test_descarga_descarta_nulos_y_convierte_a_float():
    abrir = lambda pedido, timeout: respuesta([["2024-01-01", 10], ["2024-02-01", None], ["2024-03-01", 12.5]])
    assert fuentes.descargar("ipc", abrir=abrir) == [("2024-01-01", 10.0), ("2024-03-01", 12.5)]


def test_envia_user_agent_propio():
    vistos = []

    def abrir(pedido, timeout):
        vistos.append(pedido.get_header("User-agent"))
        return respuesta([["2024-01-01", 1]])

    fuentes.descargar("ipc", abrir=abrir)
    assert vistos == [fuentes.USER_AGENT]


def test_reintenta_ante_5xx_y_luego_funciona():
    llamadas = []

    def abrir(pedido, timeout):
        llamadas.append(1)
        if len(llamadas) < 3:
            raise error_http(503)
        return respuesta([["2024-01-01", 1]])

    esperas = []
    assert fuentes.descargar("ipc", abrir=abrir, dormir=esperas.append) == [("2024-01-01", 1.0)]
    assert len(llamadas) == 3 and len(esperas) == 2


def test_un_4xx_no_se_reintenta():
    llamadas = []

    def abrir(pedido, timeout):
        llamadas.append(1)
        raise error_http(403)

    with pytest.raises(urllib.error.HTTPError):
        fuentes.descargar("ipc", abrir=abrir, dormir=lambda s: None)
    assert len(llamadas) == 1


def test_falla_con_mensaje_claro_tras_agotar_reintentos():
    def abrir(pedido, timeout):
        raise urllib.error.URLError("sin red")

    with pytest.raises(RuntimeError, match="ipc"):
        fuentes.descargar("ipc", abrir=abrir, reintentos=2, dormir=lambda s: None)


def test_serie_vacia_es_error():
    with pytest.raises(RuntimeError):
        fuentes.descargar("ipc", abrir=lambda p, timeout: respuesta([["2024-01-01", None]]), reintentos=1)


@pytest.fixture
def con():
    conexion = carga.conectar(":memory:")
    yield conexion
    conexion.close()


def test_upsert_es_idempotente(con):
    filas = [("2024-01-01", 1.0), ("2024-02-01", 2.0)]
    carga.upsert(con, "ipc", filas)
    carga.upsert(con, "ipc", filas)
    assert con.execute("SELECT count(*) FROM raw.series_raw").fetchone()[0] == 2


def test_upsert_actualiza_valor_revisado(con):
    carga.upsert(con, "ipc", [("2024-01-01", 1.0)])
    carga.upsert(con, "ipc", [("2024-01-01", 1.5)])
    assert con.execute("SELECT valor FROM raw.series_raw").fetchone()[0] == 1.5


def test_series_distintas_con_misma_fecha_conviven(con):
    carga.upsert(con, "ipc", [("2024-01-01", 1.0)])
    carga.upsert(con, "emae", [("2024-01-01", 2.0)])
    assert con.execute("SELECT count(*) FROM raw.series_raw").fetchone()[0] == 2


def test_snapshot_ida_y_vuelta(con, tmp_path):
    for nombre in fuentes.SERIES:
        carga.upsert(con, nombre, [("2024-01-01", 1.25), ("2024-02-01", 3.0)])
    carga.guardar_snapshot(con, tmp_path)
    otra = carga.conectar(":memory:")
    assert set(carga.cargar_desde_snapshot(otra, tmp_path).values()) == {2}
    assert otra.execute("SELECT valor FROM raw.series_raw WHERE serie='ipc' ORDER BY fecha").fetchall() == [(1.25,), (3.0,)]


def test_frescura_informa_ultima_fecha(con):
    carga.upsert(con, "ipc", [("2024-01-01", 1.0), ("2024-05-01", 2.0)])
    df = carga.frescura(con)
    assert df.loc[0, "ultima_fecha"].strftime("%Y-%m-%d") == "2024-05-01" and df.loc[0, "filas"] == 2
