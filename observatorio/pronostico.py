"""Backtest honesto: ¿alguna regla con dólar, salarios y actividad le gana a "el mes que viene = este mes"?

Convención de tiempo. El *origen* t es el momento en que ya salió el IPC del mes t y se quiere anticipar
el IPC del mes t+1. Con la información publicada hasta ahí:
  - inflación: hasta t
  - dólar: promedio del mes t (se conoce en tiempo real)
  - salarios y EMAE: hasta t-2 (el INDEC los publica con ~2 meses de demora)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

REZAGO_PUBLICACION = 2  # meses de demora de salarios y EMAE
MIN_ENTRENAMIENTO = 36  # orígenes mínimos antes de empezar a evaluar
QUIEBRE = pd.Timestamp("2024-01-01")  # después de la salida del cepo y la devaluación de dic-2023

MODELOS: dict[str, list[str]] = {
    "ar2": ["y0", "y1"],
    "arx_dolar": ["y0", "y1", "dolar0"],
    "arx_completo": ["y0", "y1", "dolar0", "salario_l", "emae_l"],
}
NOMBRES = ["naive", "media3", *MODELOS]


def armar_dataset(panel: pd.DataFrame) -> pd.DataFrame:
    """Una fila por origen t. `objetivo` es la inflación de t+1 (NaN en el último origen: ese es el pronóstico real)."""
    p = panel.sort_values("mes").reset_index(drop=True)
    pasos = p["mes"].diff().dropna().dt.days
    if not pasos.between(28, 31).all():
        raise ValueError("El panel tiene meses faltantes: el rezago por posición sería incorrecto.")
    d = pd.DataFrame({"origen": p["mes"]})
    d["mes_objetivo"] = d["origen"] + pd.DateOffset(months=1)
    d["objetivo"] = p["inflacion_m"].shift(-1)
    d["y0"] = p["inflacion_m"]
    d["y1"] = p["inflacion_m"].shift(1)
    d["y2"] = p["inflacion_m"].shift(2)
    d["dolar0"] = p["dolar_var_m"]
    d["salario_l"] = p["salario_var_m"].shift(REZAGO_PUBLICACION)
    d["emae_l"] = p["emae_var_a"].shift(REZAGO_PUBLICACION)
    return d.set_index("origen", drop=False)


def _ajustar_predecir(entrenamiento: pd.DataFrame, fila: pd.Series, columnas: list[str]) -> float:
    ent = entrenamiento.dropna(subset=[*columnas, "objetivo"])
    modelo = sm.OLS(ent["objetivo"], sm.add_constant(ent[columnas], has_constant="add")).fit()
    x = np.r_[1.0, fila[columnas].to_numpy(dtype=float)]
    return float(x @ modelo.params.to_numpy())


def predecir_origen(d: pd.DataFrame, origen: pd.Timestamp) -> dict[str, float]:
    """Predicciones para el mes siguiente a `origen`, usando solo lo publicado hasta `origen`.

    Se entrena con los orígenes anteriores: el objetivo del origen s es la inflación de s+1,
    que recién se conoce en s+1; por eso `s < origen` y no `s <= origen`.
    """
    fila = d.loc[origen]
    pasado = d[d["origen"] < origen]
    pred = {"naive": fila["y0"], "media3": float(np.mean([fila["y0"], fila["y1"], fila["y2"]]))}
    for nombre, columnas in MODELOS.items():
        pred[nombre] = _ajustar_predecir(pasado, fila, columnas)
    return pred


def backtest(d: pd.DataFrame, min_entrenamiento: int = MIN_ENTRENAMIENTO) -> pd.DataFrame:
    """Ventana expansiva, un reajuste por origen. Solo orígenes con todos los datos y el objetivo ya publicado."""
    completos = d.dropna(subset=["objetivo", "y0", "y1", "y2", "dolar0", "salario_l", "emae_l"])
    filas = []
    for k, origen in enumerate(completos["origen"]):
        if k < min_entrenamiento:
            continue
        fila = completos.loc[origen]
        filas.append({"origen": origen, "mes_objetivo": fila["mes_objetivo"], "real": fila["objetivo"],
                      **predecir_origen(d, origen)})
    return pd.DataFrame(filas)


def pronostico_actual(d: pd.DataFrame) -> dict:
    """Pronóstico para el mes que todavía no tiene IPC (el último origen del panel)."""
    origen = d["origen"].iloc[-1]
    return {"origen": origen, "mes_objetivo": d["mes_objetivo"].iloc[-1], **predecir_origen(d, origen)}


def errores(pred: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({n: pred[n] - pred["real"] for n in NOMBRES})


def metricas(pred: pd.DataFrame) -> pd.DataFrame:
    e = errores(pred)
    tabla = pd.DataFrame({"mae": e.abs().mean(), "rmse": np.sqrt((e**2).mean())})
    tabla["mae_vs_naive_pct"] = (tabla["mae"] / tabla.loc["naive", "mae"] - 1) * 100
    tabla["n"] = len(pred)
    return tabla


def diferencial_bootstrap(pred: pd.DataFrame, modelo: str, bloque: int = 3, remuestreos: int = 5000,
                          nivel: float = 0.90, semilla: int = 42) -> dict:
    """IC por bootstrap de bloques del ahorro de error absoluto vs naive: media(|e_naive| - |e_modelo|).

    Positivo = el modelo se equivoca menos que naive. Si el intervalo incluye 0, no hay evidencia de mejora.
    Se usan bloques porque los errores mensuales están autocorrelacionados.
    """
    e = errores(pred)
    d = (e["naive"].abs() - e[modelo].abs()).to_numpy()
    n = len(d)
    rng = np.random.default_rng(semilla)
    bloques = int(np.ceil(n / bloque))
    medias = np.empty(remuestreos)
    for i in range(remuestreos):
        inicios = rng.integers(0, n - bloque + 1, size=bloques)
        muestra = np.concatenate([d[j:j + bloque] for j in inicios])[:n]
        medias[i] = muestra.mean()
    bajo, alto = np.quantile(medias, [(1 - nivel) / 2, 1 - (1 - nivel) / 2])
    return {"modelo": modelo, "ahorro_medio": float(d.mean()), "ic_bajo": float(bajo), "ic_alto": float(alto),
            "significativo": bool(bajo > 0), "n": n}


def evaluar(pred: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Métricas y bootstrap para toda la muestra y para el período posterior al quiebre de dic-2023."""
    resultado = {}
    for nombre, sub in {"completa": pred, "desde_2024": pred[pred["mes_objetivo"] >= QUIEBRE]}.items():
        sub = sub.reset_index(drop=True)
        if len(sub) < 6:
            continue
        m = metricas(sub).reset_index(names="modelo")
        b = pd.DataFrame([diferencial_bootstrap(sub, n) for n in NOMBRES if n != "naive"])
        m = m.merge(b.drop(columns="n"), on="modelo", how="left")
        m.insert(0, "muestra", nombre)
        resultado[nombre] = m
    return resultado


def ejecutar(con) -> dict:
    """Lee el mart, corre el backtest y guarda los resultados en el esquema `resultados`."""
    panel = con.execute("select * from marts.mart_mensual order by mes").df()
    panel["mes"] = pd.to_datetime(panel["mes"])
    d = armar_dataset(panel)
    pred = backtest(d)
    tablas = pd.concat(evaluar(pred).values(), ignore_index=True)
    actual = pd.DataFrame([pronostico_actual(d)])
    con.execute("CREATE SCHEMA IF NOT EXISTS resultados")
    for nombre, df in {"predicciones": pred, "metricas": tablas, "pronostico_actual": actual}.items():
        con.register("tmp_df", df)
        con.execute(f"CREATE OR REPLACE TABLE resultados.{nombre} AS SELECT * FROM tmp_df")
        con.unregister("tmp_df")
    return {"predicciones": pred, "metricas": tablas, "pronostico_actual": actual}
