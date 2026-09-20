"""Observatorio de inflación: la pregunta, la respuesta y la evidencia."""
import os
from pathlib import Path

import duckdb
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

RUTA_DB = Path(os.environ.get("OBS_DB", Path(__file__).resolve().parent.parent / "observatorio.duckdb"))
ETIQUETAS = {"naive": "Igual al mes anterior", "media3": "Promedio 3 meses", "ar2": "AR(2)",
             "arx_dolar": "AR(2) + dólar", "arx_completo": "AR(2) + dólar + salarios + actividad"}

st.set_page_config(page_title="Observatorio de inflación", page_icon="📈", layout="wide")


@st.cache_data(ttl=300)
def leer(tabla: str, ruta: str) -> pd.DataFrame:
    con = duckdb.connect(ruta, read_only=True)
    try:
        return con.execute(f"select * from {tabla}").df()
    finally:
        con.close()


if not RUTA_DB.exists():
    st.error("No encontré la base. Corré `python -m observatorio.cli ingesta` y `dbt build` (ver README).")
    st.stop()

ruta = str(RUTA_DB)
mart = leer("marts.mart_mensual", ruta)
pred = leer("resultados.predicciones", ruta)
metricas = leer("resultados.metricas", ruta)
actual = leer("resultados.pronostico_actual", ruta).iloc[0]
frescura = leer("(select serie, max(fecha) as ultima_fecha, count(*) as filas from raw.series_raw group by 1)", ruta)

st.title("¿Se puede anticipar la inflación del mes que viene?")
st.markdown("Probé si el **dólar, los salarios y la actividad** ayudan a pronosticar el IPC del mes siguiente mejor que "
            "la regla más simple: *el mes que viene va a dar lo mismo que este mes*. Backtest mensual con ventana "
            "expansiva y solo información publicada hasta cada fecha.")

muestra = st.radio("Período evaluado", ["completa", "desde_2024"], horizontal=True,
                   format_func=lambda m: "Toda la muestra" if m == "completa" else "Desde ene-2024 (post-devaluación)")
m = metricas[metricas["muestra"] == muestra].copy()
m["Modelo"] = m["modelo"].map(ETIQUETAS)

st.subheader("Error de cada modelo")
tabla = m[["Modelo", "mae", "rmse", "mae_vs_naive_pct", "ahorro_medio", "ic_bajo", "ic_alto"]].rename(columns={
    "mae": "Error medio (pp)", "rmse": "RMSE (pp)", "mae_vs_naive_pct": "Error vs. ingenuo (%)",
    "ahorro_medio": "Ahorro medio (pp)", "ic_bajo": "IC90 bajo", "ic_alto": "IC90 alto"})
st.dataframe(tabla.style.format(precision=2, na_rep="—"), hide_index=True, use_container_width=True)
st.caption("Ahorro medio = cuánto menos se equivoca el modelo que la regla ingenua (en puntos porcentuales); "
           "positivo es mejor. IC90 = intervalo por bootstrap: si incluye el 0, no hay evidencia de mejora.")
mejores = m[(m["modelo"] != "naive") & (m["significativo"] == True)]  # noqa: E712
if mejores.empty:
    st.info("**Ningún modelo le gana a la regla ingenua con evidencia estadística**: el intervalo del ahorro de error "
            "incluye el cero o es negativo. La inflación mensual es muy persistente y esa persistencia ya está en "
            "el último dato.")
else:
    st.success("Modelos con ahorro significativo: " + ", ".join(mejores["Modelo"]))

st.subheader("Pronóstico para " + pd.Timestamp(actual["mes_objetivo"]).strftime("%m/%Y"))
cols = st.columns(len(ETIQUETAS))
for c, n in zip(cols, ETIQUETAS):
    c.metric(ETIQUETAS[n], f"{actual[n]:.2f}%")
dispersion = max(actual[n] for n in ETIQUETAS) - min(actual[n] for n in ETIQUETAS)
st.caption(f"Entre el modelo más bajo y el más alto hay {dispersion:.2f} pp de diferencia. "
           "La tabla de arriba dice cuánto confiar en cada uno.")

st.subheader("Lo que pasó vs. lo que dijo cada modelo")
sel = st.multiselect("Modelos", list(ETIQUETAS), default=["naive", "arx_dolar"], format_func=ETIQUETAS.get)
p = pred if muestra == "completa" else pred[pd.to_datetime(pred["mes_objetivo"]) >= "2024-01-01"]
fig = go.Figure(go.Scatter(x=p["mes_objetivo"], y=p["real"], name="IPC real", line=dict(color="#111", width=3)))
for n in sel:
    fig.add_trace(go.Scatter(x=p["mes_objetivo"], y=p[n], name=ETIQUETAS[n], line=dict(dash="dot")))
fig.update_layout(height=380, yaxis_title="Inflación mensual (%)", margin=dict(t=10), legend=dict(orientation="h", y=-0.2))
st.plotly_chart(fig, use_container_width=True)

st.subheader("El panel de datos")
fig2 = go.Figure()
fig2.add_trace(go.Bar(x=mart["mes"], y=mart["inflacion_m"], name="Inflación mensual (%)", marker_color="#2b6cb0"))
fig2.add_trace(go.Scatter(x=mart["mes"], y=mart["dolar_var_m"], name="Dólar, var. mensual (%)", line=dict(color="#dd6b20")))
fig2.update_layout(height=330, margin=dict(t=10), legend=dict(orientation="h", y=-0.2))
st.plotly_chart(fig2, use_container_width=True)

with st.expander("Limitaciones y decisiones"):
    st.markdown(
        "- Solo hay ~117 meses de IPC nacional en la serie pública (desde dic-2016): son ~77 evaluaciones, "
        "y el período incluye un quiebre de régimen (dic-2023). Por eso se reporta también desde 2024.\n"
        "- Salarios y EMAE se publican con ~2 meses de demora: el modelo solo usa lo que ya estaba publicado.\n"
        "- El IC es un bootstrap por bloques del ahorro de error absoluto vs. la regla ingenua.\n"
        "- No es asesoramiento financiero.")

st.sidebar.header("Frescura de los datos")
frescura["ultima_fecha"] = pd.to_datetime(frescura["ultima_fecha"]).dt.strftime("%Y-%m-%d")
st.sidebar.dataframe(frescura.rename(columns={"serie": "Serie", "ultima_fecha": "Último dato", "filas": "Filas"}),
                     hide_index=True)
st.sidebar.caption("Fuente: API de series de tiempo de datos.gob.ar (INDEC, BCRA, BNA).")
