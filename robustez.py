"""Chequeos de robustez del backtest (exploratorio, no forma parte del pipeline)."""
import numpy as np
import pandas as pd
import statsmodels.api as sm

from observatorio import carga, pronostico as pr

pd.set_option("display.width", 220)
con = carga.conectar()
panel = con.execute("select * from marts.mart_mensual order by mes").df()
panel["mes"] = pd.to_datetime(panel["mes"])
d = pr.armar_dataset(panel)
comp = d.dropna(subset=["objetivo", "y0", "y1", "y2", "dolar0", "salario_l", "emae_l"])

# 1) ventana móvil de 36 orígenes
filas = []
for k, o in enumerate(comp["origen"]):
    if k < 36:
        continue
    fila = comp.loc[o]
    ent = d[d["origen"] < o].dropna(subset=["objetivo", "y0", "y1", "dolar0"]).tail(36)
    m = sm.OLS(ent["objetivo"], sm.add_constant(ent[["y0", "y1", "dolar0"]])).fit()
    p = float(np.r_[1, fila[["y0", "y1", "dolar0"]].to_numpy(float)] @ m.params.to_numpy())
    filas.append((o, fila["objetivo"], fila["y0"], p))
r = pd.DataFrame(filas, columns=["o", "real", "naive", "movil"])
for nombre, sub in {"completa": r, "desde_2024": r[r["o"] >= "2023-12-01"]}.items():
    print(nombre, "MAE naive", round((sub.naive - sub.real).abs().mean(), 3), "MAE ventana movil arx_dolar",
          round((sub.movil - sub.real).abs().mean(), 3))

# 2) donde falla naive
e = (comp["y0"] - comp["objetivo"]).abs().sort_values(ascending=False).head(6)
print("\nMayores errores de naive (origen -> |error| pp):")
print(pd.DataFrame({"origen": e.index.strftime("%Y-%m"), "objetivo": comp.loc[e.index, "objetivo"].round(1),
                    "y0": comp.loc[e.index, "y0"].round(1), "err": e.round(1).to_numpy()}).to_string(index=False))

# 3) relación entre salto del dólar y aceleración de la inflación
cambio = comp["objetivo"] - comp["y0"]
for nombre, mask in {"completa": comp.index == comp.index, "desde_2024": comp["mes_objetivo"] >= "2024-01-01"}.items():
    print(nombre, "corr(dolar_var_t, aceleracion t+1) =", round(np.corrcoef(comp.loc[mask, "dolar0"], cambio[mask])[0, 1], 3),
          "n =", int(mask.sum()))
print("autocorr inflacion mensual (lag1):", round(panel["inflacion_m"].autocorr(1), 3))
print("share de meses con |error naive| < 1pp:", round(((comp["y0"] - comp["objetivo"]).abs() < 1).mean(), 3))
