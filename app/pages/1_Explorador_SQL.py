"""Explorador SQL: consultas de solo lectura sobre los datos del observatorio."""
import streamlit as st

from _base import ruta_base
from observatorio import consultas

st.set_page_config(page_title="Explorador SQL", page_icon="🔎", layout="wide")

ruta = ruta_base()

st.title("Explorador SQL")
st.markdown("Consultá con SQL los mismos datos del observatorio (IPC, dólar, salarios, actividad y el backtest). "
            "Elegí un ejemplo o escribí el tuyo. Es DuckDB en **solo lectura**: se permite una sola sentencia "
            f"`SELECT` por vez, hasta {consultas.MAX_FILAS} filas y {consultas.TIMEOUT_S:g} segundos.")

with st.expander("Tablas disponibles"):
    st.dataframe(consultas.tablas_disponibles(ruta).rename(columns={"tabla": "Tabla", "columnas": "Columnas"}),
                 hide_index=True, use_container_width=True)

nombre = st.selectbox("Ejemplos", list(consultas.EJEMPLOS), index=0)
ejemplo_nuevo = st.session_state.get("_ejemplo") != nombre
if ejemplo_nuevo:  # al cambiar de ejemplo se reemplaza el texto del editor y se ejecuta solo
    st.session_state["_ejemplo"] = nombre
    st.session_state["sql"] = consultas.EJEMPLOS[nombre]

sql = st.text_area("Tu consulta", key="sql", height=240)

if st.button("Ejecutar", type="primary") or ejemplo_nuevo:
    try:
        st.session_state["resultado"] = consultas.ejecutar(ruta, sql)
        st.session_state["error"] = None
    except consultas.ConsultaRechazada as error:
        st.session_state["error"] = str(error)

if st.session_state.get("error"):
    st.error(st.session_state["error"])
elif st.session_state.get("resultado") is not None:
    res = st.session_state["resultado"]
    st.caption(f"{len(res.tabla)} filas" + (f" (se muestran las primeras {consultas.MAX_FILAS})" if res.truncado else ""))
    st.dataframe(res.tabla, hide_index=True, use_container_width=True)
