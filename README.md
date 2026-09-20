# Observatorio de inflación argentina

**¿Se puede anticipar la inflación del mes que viene con el dólar, la actividad y los salarios, mejor que con una regla ingenua ("el mes que viene da lo mismo que este mes")?**

Respuesta corta, después de un backtest de 77 meses: **no**. Ningún modelo le gana a la regla ingenua con evidencia estadística, y el proyecto está armado para poder decir eso con honestidad.

| Modelo (77 meses, 2020-04 a 2026-08) | Error medio | vs. ingenuo | Ahorro medio de error, IC 90% |
|---|---|---|---|
| **Igual al mes anterior** | **1,18 pp** | — | — |
| Promedio de 3 meses | 1,48 pp | +25% | [-0,60; -0,08] |
| AR(2) | 1,28 pp | +9% | [-0,25; +0,03] |
| AR(2) + dólar | 1,28 pp | +9% | [-0,22; +0,01] |
| AR(2) + dólar + salarios + actividad | 1,39 pp | +18% | [-0,38; -0,08] |

Desde enero de 2024 (32 meses, después del quiebre de la devaluación de dic-2023) pasa lo mismo: el mejor modelo (AR + dólar) queda 6% peor que el ingenuo y su intervalo incluye el cero. Detalle en [`resultados/`](resultados) y [`DECISIONES.md`](DECISIONES.md).

Por qué es así: la inflación mensual argentina tiene autocorrelación de 0,85; casi toda la información ya está en el último dato. Donde todos fallan fuerte es en los saltos: para dic-2023 el ingenuo dijo 12,8%, los modelos con dólar 10,6%, y fue 25,5%. La devaluación ocurrió *después* de la información disponible en el origen, así que ningún modelo mensual podía verla venir.

## Qué hace el pipeline

```
datos.gob.ar (API)          DuckDB                    dbt                        Python                Streamlit
IPC, salarios, EMAE,  ─►  raw.series_raw  ─►  staging (5 vistas) ─► mart_mensual ─► backtest ─► resultados ─► app
dólar, reservas          upsert idempotente   + 22 tests de datos                    rolling-origin    (CSV + DuckDB)
                                                                                     + bootstrap
                          └──────────────────── orquestado con Dagster (asset checks + corrida diaria) ─────────────┘
```

- **Ingesta** (`observatorio/fuentes.py`, `carga.py`): descarga con reintentos ante 5xx/red (un 4xx no se reintenta) y User-Agent propio, porque la API responde 403 al de Python por defecto. La carga es idempotente: clave primaria `(serie, fecha)` y `INSERT OR REPLACE`, así una serie revisada actualiza su valor y correr dos veces no duplica nada.
- **Modelado** (`dbt/`): staging calcula las variaciones sobre toda la historia (para no perder los primeros 12 meses del EMAE interanual) y el mart las une por mes. 22 tests: unicidad, no nulos, y tres singulares que cortan el pipeline: **meses faltantes en el IPC**, **inflación mensual fuera de -5%..50%** y **meses de dólar con pocos datos**.
- **Backtest** (`observatorio/pronostico.py`): ventana expansiva, un reajuste por mes, solo con información publicada hasta cada fecha (salarios y EMAE con 2 meses de demora). Métricas MAE y RMSE, e intervalo por bootstrap de bloques del ahorro de error contra el ingenuo.
- **Orquestación** (`observatorio/definiciones.py`): tres assets de Dagster (`series_crudas` → `modelos_dbt` → `backtest`), un asset check de frescura y una corrida diaria. Si un test de dbt falla, el backtest no corre.
- **App** (`app/streamlit_app.py`): la pregunta, la tabla de errores con su intervalo, el pronóstico del mes próximo, y los gráficos.

## Cómo correrlo

Necesita Python 3.12. No usa Docker ni servicios externos: la base es un archivo DuckDB.

```bash
pip install -r requirements.txt
python -m observatorio.cli actualizar               # baja las series, dbt build (con tests) y backtest
streamlit run app/streamlit_app.py
```

Sin red, con la copia versionada de los datos (`datos/snapshot/`):

```bash
python -m observatorio.cli actualizar --fuente snapshot
```

Con Dagster (UI en http://localhost:3000, corrida diaria a las 9:00 de Buenos Aires):

```bash
dagster dev -m observatorio.definiciones
```

## Tests

```bash
pytest -q        # 28 tests, ~4 minutos (varios corren dbt y Dagster de punta a punta)
```

Además de los tests de rutina, hay cuatro que me importan más:

- **Sin fuga de información:** se altera todo lo que ocurre después de un origen y la predicción en ese origen no cambia.
- **El backtest distingue señal de ruido:** con una serie mean-reverting el AR le gana al ingenuo *y* el bootstrap lo detecta; con una caminata aleatoria (donde el ingenuo es óptimo) los modelos con regresores irrelevantes casi nunca salen "significativos".
- **Los tests de datos de dbt fallan de verdad:** se borra un mes del IPC y se triplica otro valor, y el pipeline se corta.
- **La app no bloquea la base:** dbt dejaba abierta su conexión a DuckDB y eso trababa a cualquier otro proceso (ver DECISIONES).

## Limitaciones

- La serie pública de IPC nacional empieza en dic-2016: son 117 meses y 77 evaluaciones. Con tan pocos datos y un quiebre de régimen, un modelo bueno pero modesto no se distingue del ingenuo; este resultado dice "no hay evidencia", no "es imposible".
- Solo se probaron 5 especificaciones (y una variante de ventana móvil como chequeo de robustez) para no inflar los falsos positivos.
- Es un ejercicio de análisis y de ingeniería de datos, no asesoramiento financiero.

## Fuentes

API de series de tiempo de [datos.gob.ar](https://datos.gob.ar/series/api/): IPC nacional (INDEC), índice de salarios (INDEC), EMAE (INDEC), tipo de cambio BNA vendedor y reservas del BCRA.

## Estructura

```
observatorio/   ingesta, carga a DuckDB, backtest, pipeline y assets de Dagster
dbt/            modelos staging + mart, tests de datos, macro de esquemas
app/            app de Streamlit
tests/          pytest (ingesta, backtest, pipeline de punta a punta, app)
datos/snapshot/ copia versionada de las 5 series (para CI y uso sin red)
resultados/     salida del último backtest en CSV
robustez.py     chequeos de robustez citados en DECISIONES.md
```
