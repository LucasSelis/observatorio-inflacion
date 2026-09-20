"""Línea de comandos: `python -m observatorio.cli actualizar [--fuente api|snapshot]` o `estado`."""
from __future__ import annotations

import argparse

from . import carga, pipeline


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="observatorio")
    p.add_argument("comando", choices=["actualizar", "estado"],
                   help="actualizar = ingesta + dbt build (con tests) + backtest; estado = frescura de los datos")
    p.add_argument("--fuente", choices=["api", "snapshot"], default="api",
                   help="api baja de datos.gob.ar; snapshot usa la copia versionada (sin red)")
    args = p.parse_args(argv)

    if args.comando == "actualizar":
        for nombre, n in pipeline.ingestar(carga.RUTA_DB, args.fuente).items():
            print(f"{nombre}: {n} filas")
        pipeline.construir_modelos(carga.RUTA_DB)
        pipeline.backtest(carga.RUTA_DB, carga.RAIZ / "resultados")
    con = carga.conectar()
    try:
        print(carga.frescura(con).to_string(index=False))
    finally:
        con.close()
    for problema in pipeline.problemas_de_frescura(carga.RUTA_DB):
        print("ATENCION:", problema)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
