import numpy as np
import pandas as pd
import pytest

from observatorio import pronostico as pr


def panel_sintetico(n=90, semilla=0, f=None):
    rng = np.random.default_rng(semilla)
    meses = pd.date_range("2017-01-01", periods=n, freq="MS")
    y = np.zeros(n)
    y[0] = 3.0
    for i in range(1, n):
        y[i] = f(y[i - 1], rng) if f else 3 + rng.normal(0, 1)
    return pd.DataFrame({
        "mes": meses,
        "inflacion_m": y,
        "dolar_var_m": rng.normal(2, 1, n),
        "salario_var_m": rng.normal(3, 1, n),
        "emae_var_a": rng.normal(0, 2, n),
    })


def test_dataset_alinea_objetivo_y_rezagos():
    p = panel_sintetico(20)
    d = pr.armar_dataset(p)
    assert d.loc["2017-05-01", "objetivo"] == p.loc[5, "inflacion_m"]      # origen mayo -> objetivo junio
    assert d.loc["2017-05-01", "y1"] == p.loc[3, "inflacion_m"]            # rezago 1 = abril
    assert d.loc["2017-05-01", "salario_l"] == p.loc[2, "salario_var_m"]   # salarios: 2 meses de demora
    assert d.loc["2017-05-01", "emae_l"] == p.loc[2, "emae_var_a"]


def test_ultimo_origen_no_tiene_objetivo_y_es_el_pronostico_real():
    d = pr.armar_dataset(panel_sintetico(60))
    assert np.isnan(d["objetivo"].iloc[-1])
    actual = pr.pronostico_actual(d)
    assert actual["mes_objetivo"] == d["origen"].iloc[-1] + pd.DateOffset(months=1)
    assert all(np.isfinite(actual[n]) for n in pr.NOMBRES)


def test_meses_faltantes_se_rechazan():
    p = panel_sintetico(30).drop(index=10)
    with pytest.raises(ValueError, match="faltantes"):
        pr.armar_dataset(p)


def test_no_hay_fuga_de_informacion_futura():
    """Cambiar todo lo que ocurre después del origen no puede modificar la predicción en ese origen."""
    p = panel_sintetico(80, semilla=1)
    origen = p.loc[60, "mes"]
    base = pr.predecir_origen(pr.armar_dataset(p), origen)
    alterado = p.copy()
    alterado.loc[61:, ["inflacion_m", "dolar_var_m", "salario_var_m", "emae_var_a"]] += 1000
    d2 = pr.armar_dataset(alterado)
    # Ojo: el objetivo del propio origen (y[61]) sí cambió, pero no debe usarse para predecirlo.
    nuevo = pr.predecir_origen(d2, origen)
    for nombre in pr.NOMBRES:
        assert nuevo[nombre] == pytest.approx(base[nombre]), nombre


def test_ar_le_gana_a_naive_cuando_hay_reversion_a_la_media():
    p = panel_sintetico(120, semilla=2, f=lambda y, rng: 3 + 0.3 * (y - 3) + rng.normal(0, 0.5))
    pred = pr.backtest(pr.armar_dataset(p))
    m = pr.metricas(pred)
    assert m.loc["ar2", "mae"] < m.loc["naive", "mae"]
    assert pr.diferencial_bootstrap(pred, "ar2")["significativo"]


def test_naive_gana_en_una_caminata_aleatoria_y_el_ic_no_lo_contradice():
    p = panel_sintetico(120, semilla=3, f=lambda y, rng: y + rng.normal(0, 1))
    pred = pr.backtest(pr.armar_dataset(p))
    assert not pr.diferencial_bootstrap(pred, "arx_completo")["significativo"]


def test_tasa_de_falsos_positivos_acotada_cuando_naive_es_lo_optimo():
    """En una caminata aleatoria naive es óptimo: regresores irrelevantes casi nunca deben salir 'significativos'.

    (Con ruido iid alrededor de una constante, naive es un mal benchmark y cualquier promedio le gana:
    por eso el caso 'sin señal' correcto es la caminata aleatoria.)
    """
    caminata = lambda y, rng: y + rng.normal(0, 1)
    positivos = 0
    for semilla in range(8):
        p = panel_sintetico(110, semilla=100 + semilla, f=caminata)
        pred = pr.backtest(pr.armar_dataset(p))
        positivos += pr.diferencial_bootstrap(pred, "arx_completo", remuestreos=300)["significativo"]
    assert positivos <= 2


def test_bootstrap_es_reproducible():
    pred = pr.backtest(pr.armar_dataset(panel_sintetico(100, semilla=5)))
    a = pr.diferencial_bootstrap(pred, "ar2", remuestreos=300)
    b = pr.diferencial_bootstrap(pred, "ar2", remuestreos=300)
    assert a == b


def test_metricas_de_un_caso_calculado_a_mano():
    pred = pd.DataFrame({"real": [1.0, 2.0], **{n: [1.0, 2.0] for n in pr.NOMBRES}})
    pred["naive"] = [2.0, 4.0]  # errores 1 y 2
    m = pr.metricas(pred)
    assert m.loc["naive", "mae"] == pytest.approx(1.5)
    assert m.loc["naive", "rmse"] == pytest.approx(np.sqrt((1 + 4) / 2))
    assert m.loc["ar2", "mae"] == 0
