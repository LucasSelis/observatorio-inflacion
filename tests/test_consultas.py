"""El explorador SQL ejecuta consultas de desconocidos en un servidor público: se prueba como si fuera un ataque."""
import time

import duckdb
import pytest

from observatorio import carga, consultas


def correr(base, sql, **kw):
    return consultas.ejecutar(base, sql, **kw)


# --- lo que sí debe funcionar -------------------------------------------------------------------------------------

@pytest.mark.parametrize("nombre", list(consultas.EJEMPLOS))
def test_todos_los_ejemplos_corren_y_devuelven_filas(base_lista, nombre):
    res = correr(base_lista, consultas.EJEMPLOS[nombre])
    assert len(res.tabla) > 0


def test_cte_y_funciones_de_ventana(base_lista):
    res = correr(base_lista, "WITH t AS (SELECT mes, lag(inflacion_m) OVER (ORDER BY mes) AS a FROM marts.mart_mensual) "
                             "SELECT count(*) AS n FROM t WHERE a IS NOT NULL")
    assert res.tabla.loc[0, "n"] > 100


def test_un_comentario_final_o_punto_y_coma_no_rompen_el_limite(base_lista):
    assert len(correr(base_lista, "SELECT 1 AS x -- hola").tabla) == 1
    assert len(correr(base_lista, "SELECT 1 AS x;").tabla) == 1


def test_limite_de_filas(base_lista):
    res = correr(base_lista, "SELECT * FROM range(5000)", max_filas=100)
    assert len(res.tabla) == 100 and res.truncado
    assert not correr(base_lista, "SELECT * FROM range(50)", max_filas=100).truncado


def test_lista_las_tablas_del_observatorio(base_lista):
    nombres = set(consultas.tablas_disponibles(base_lista)["tabla"])
    assert {"marts.mart_mensual", "resultados.predicciones", "raw.series_raw"} <= nombres


# --- lo que debe rechazarse ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("sql", [
    "DROP TABLE marts.mart_mensual",
    "DELETE FROM raw.series_raw",
    "INSERT INTO raw.series_raw VALUES ('x', DATE '2020-01-01', 1, now())",
    "UPDATE raw.series_raw SET valor = 0",
    "CREATE TABLE robo AS SELECT * FROM marts.mart_mensual",
    "COPY marts.mart_mensual TO 'fuga.csv'",
    "ATTACH 'otra.duckdb' AS otra",
    "INSTALL httpfs",
    "LOAD httpfs",
    "SET enable_external_access = true",
    "PRAGMA database_list",
    "EXPORT DATABASE 'fuga'",
])
def test_sentencias_que_no_son_select_se_rechazan(base_lista, sql):
    with pytest.raises(consultas.ConsultaRechazada):
        correr(base_lista, sql)


def test_varias_sentencias_se_rechazan(base_lista):
    with pytest.raises(consultas.ConsultaRechazada, match="una consulta"):
        correr(base_lista, "SELECT 1; DROP TABLE marts.mart_mensual")


def test_consulta_vacia_o_con_error_de_sintaxis_da_mensaje_claro(base_lista):
    with pytest.raises(consultas.ConsultaRechazada, match="Escribí"):
        correr(base_lista, "   ")
    with pytest.raises(consultas.ConsultaRechazada, match="interpretar"):
        correr(base_lista, "SELEC 1")


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM read_text('C:/Windows/win.ini')",
    "SELECT * FROM glob('*')",
    "SELECT * FROM read_csv('https://example.com/x.csv')",
    "SELECT * FROM read_parquet('x.parquet')",
])
def test_no_puede_leer_archivos_ni_internet(base_lista, sql):
    with pytest.raises(consultas.ConsultaRechazada):
        correr(base_lista, sql)


def test_el_error_no_filtra_rutas_ni_trazas(base_lista):
    with pytest.raises(consultas.ConsultaRechazada) as e:
        correr(base_lista, "SELECT columna_que_no_existe FROM marts.mart_mensual")
    assert "\n" not in str(e.value) and "Traceback" not in str(e.value) and str(base_lista) not in str(e.value)


def test_una_consulta_pesada_se_cancela_por_tiempo(base_lista):
    t0 = time.time()
    with pytest.raises(consultas.ConsultaRechazada, match="segundos"):
        correr(base_lista, "SELECT count(*) FROM range(3000000000) AS r(n) WHERE n % 7 = (random() * 7)::int", timeout_s=1)
    assert time.time() - t0 < 8


def test_los_ataques_no_dejaron_rastro(base_lista, tmp_path):
    """Después de todo lo anterior, la base sigue intacta y no se escribió nada en el directorio de trabajo."""
    con = carga.abrir_solo_lectura(base_lista)
    try:
        assert con.execute("select count(*) from marts.mart_mensual").fetchone()[0] > 100
        assert con.execute("select count(*) from raw.series_raw").fetchone()[0] > 5000
    finally:
        con.close()
    import pathlib
    for basura in ("fuga.csv", "otra.duckdb", "fuga", "robo"):
        assert not pathlib.Path(basura).exists()


def test_la_configuracion_no_se_puede_cambiar_desde_una_consulta(base_lista):
    con = carga.abrir_solo_lectura(base_lista)
    try:
        with pytest.raises(duckdb.Error):
            con.execute("SET enable_external_access = true")
    finally:
        con.close()
