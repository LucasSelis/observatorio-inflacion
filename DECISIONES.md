# Decisiones de diseño

Registro de las decisiones no obvias del proyecto, con el porqué y, cuando corresponde, qué salió mal.

## Datos

**1. Carga idempotente con clave `(serie, fecha)`.** La API revisa valores históricos (sobre todo salarios y EMAE). Con `INSERT OR REPLACE` una revisión pisa el valor viejo y correr el pipeline dos veces no duplica filas. Está testeado.

**2. Snapshot versionado de las series.** `datos/snapshot/*.csv` es una copia de lo que devolvió la API. El CI y los tests corren contra eso: un test que falla porque datos.gob.ar estuvo caído no me dice nada sobre mi código. La ingesta contra la API real refresca el snapshot.

**3. User-Agent propio.** La API responde 403 al User-Agent por defecto de `urllib`. Lo descubrí en otro proyecto corriendo contra la API real: los tests con datos simulados estaban en verde y la app no funcionaba. Acá lo cubre un test que verifica el header, y los reintentos no repiten un 4xx.

**4. Las variaciones se calculan en staging, sobre toda la historia.** El EMAE interanual necesita 12 meses previos; el IPC solo empieza en dic-2016. Si se calculara después de unir por mes se perderían justo esos meses.

**5. Se descartó la variación mensual del EMAE.** La serie usada es la *sin desestacionalizar*: su variación mensual daba saltos de +15% que son estacionalidad, no información. Solo se expone la interanual.

**6. El dólar se resume a promedio y cierre mensual.** Es diario e incluye fines de semana arrastrados, así que el promedio del mes es una medida razonable de "el dólar de ese mes".

## Backtest

**7. Convención de tiempo explícita.** El origen `t` es cuando ya salió el IPC de `t`; se pronostica `t+1`. Con lo publicado hasta ahí: inflación hasta `t`, dólar de `t`, y salarios y EMAE hasta `t-2` (el INDEC los publica con ~2 meses de demora). Usar el salario de `t` sería hacer trampa: en el momento real no existe.

**8. Entrenar solo con orígenes anteriores (`s < t`).** El objetivo del origen `s` es la inflación de `s+1`, que recién se conoce en `s+1`. Entrenar con `s = t` usaría el dato que se quiere pronosticar. Hay un test que altera todo lo posterior al origen y verifica que la predicción no cambia.

**9. Ventana expansiva, reajuste en cada origen, 36 orígenes mínimos.** Es lo que se podría haber hecho en tiempo real.

**10. Benchmark ingenuo, y por qué importa.** Escribiendo los tests cometí un error instructivo: probé "ruido puro" con datos iid alrededor de una constante y los modelos le ganaban al ingenuo "sin tener información". No era un bug: con iid, repetir el último dato es un mal pronóstico (varianza del error 2σ²) y cualquier promedio lo supera. El caso "sin señal" correcto es una caminata aleatoria, donde el ingenuo es óptimo. Con la inflación real pasa lo opuesto: autocorrelación 0,85, el ingenuo es fuerte. Ganarle a un benchmark débil no prueba nada.

**11. Intervalo por bootstrap de bloques.** Los errores de meses consecutivos están correlacionados, así que un bootstrap simple daría intervalos demasiado angostos. Bloques de 3 meses, 5.000 remuestreos, semilla fija, nivel 90%. El estadístico es el ahorro medio de error absoluto contra el ingenuo; "significativo" significa que el IC entero es positivo.

**12. Se reporta también desde 2024.** Dic-2023 (salida del cepo y devaluación) es un quiebre de régimen; mezclar antes y después puede esconder o inventar un resultado. En ambas muestras la conclusión es la misma.

**13. Un resultado negativo se reporta como negativo.** Ningún modelo le gana al ingenuo. No agregué variantes hasta encontrar una que "funcione": con 77 evaluaciones, probar muchas especificaciones garantiza un falso positivo. Se probaron 5 modelos y un chequeo de robustez.

**14. Chequeo de robustez (`robustez.py`).** AR(2) + dólar con ventana móvil de 36 meses en vez de expansiva: error medio 1,55 pp (vs. 1,18 del ingenuo) en toda la muestra y 1,58 (vs. 1,02) desde 2024. Peor, no mejor. La conclusión no depende de la ventana.

**15. Lo que no interpreté.** En el análisis exploratorio, el salto del dólar de un mes correlaciona *negativamente* con la aceleración de la inflación del mes siguiente (-0,29 en toda la muestra, -0,63 desde 2024). Contra la intuición de traspaso a precios. Casi seguro es un artefacto: los meses de dólar más alto (dic-2023: +80%) preceden a la desaceleración por reversión a la media y por el ajuste posterior. No lo presento como hallazgo.

## Ingeniería

**16. Los tests de dbt tienen que poder fallar.** Los 28 tests de dbt dieron verde a la primera, lo cual no prueba nada. Por eso hay tests de pytest que borran un mes del IPC y triplican otro valor y verifican que `dbt build` corta el pipeline.

**17. dbt bloqueaba el archivo DuckDB.** Al correr dbt dentro del proceso (Dagster, tests) `dbt-duckdb` deja una conexión de clase abierta; `cleanup_connections()` solo la des-referencia sin cerrarla. Resultado: mientras el proceso de Dagster vivía, la app de Streamlit no podía abrir la base (DuckDB permite un solo escritor por archivo y no deja mezclar configuraciones). Ahora `pipeline._soltar_duckdb()` la cierra explícitamente. Usa un atributo interno (`_ENV`), por eso hay un test de regresión que abre la base en solo lectura justo después del build.

**18. El umbral de frescura del dólar es de 35 días, no 7.** Al correr el pipeline en sept-2026 el asset check alertó: la serie diaria del dólar en datos.gob.ar terminaba el 31-ago. La fuente publica con ~3 semanas de demora; con un umbral de 7 días la alerta estaría siempre encendida y nadie la miraría. El IPC tiene 75 días (sale ~45 días después del mes).

**19. Sin Docker.** DuckDB es un archivo y dbt corre en el mismo proceso. Menos piezas, menos fricción para quien quiera reproducirlo; en producción la base sería un warehouse y dbt correría como job.

**20. Orquestación fina.** Los pasos son funciones en `pipeline.py`; los assets de Dagster solo las llaman. Así la misma lógica corre por CLI (`observatorio.cli`), en tests y en Dagster.
