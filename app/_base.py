"""Preparación de la base para las páginas de la app (local o en un servidor sin mi archivo DuckDB)."""
import os
import sys
import tempfile
from pathlib import Path

import streamlit as st

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:  # las páginas se ejecutan como scripts: hay que poder importar `observatorio`
    sys.path.insert(0, str(RAIZ))

from observatorio import pipeline  # noqa: E402


@st.cache_resource(show_spinner="Preparando los datos (solo la primera visita, ~20 segundos)…")
def _preparar(candidata: str) -> str:
    """Usa la base local si está lista; si no, la arma desde el snapshot en una carpeta temporal."""
    if pipeline.base_lista(candidata):
        return candidata
    temporal = Path(tempfile.gettempdir()) / "observatorio_app.duckdb"
    pipeline.asegurar_base(temporal)
    return str(temporal)


def ruta_base() -> str:
    # La candidata es argumento de la función cacheada: cambia la clave si cambia OBS_DB (tests, otro entorno).
    return _preparar(str(Path(os.environ.get("OBS_DB", RAIZ / "observatorio.duckdb"))))
