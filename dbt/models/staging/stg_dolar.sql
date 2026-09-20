-- La serie es diaria: se resume a promedio y cierre de cada mes.
with diaria as (
    select cast(fecha as date) as fecha, valor
    from {{ source('raw', 'series_raw') }}
    where serie = 'dolar'
),

mensual as (
    select
        cast(date_trunc('month', fecha) as date) as mes,
        avg(valor) as dolar_prom,
        arg_max(valor, fecha) as dolar_cierre,
        count(*) as dias_con_dato
    from diaria
    group by 1
)

select
    mes,
    dolar_prom,
    dolar_cierre,
    dias_con_dato,
    (dolar_prom / lag(dolar_prom) over (order by mes) - 1) * 100 as dolar_var_m,
    (dolar_cierre / lag(dolar_cierre) over (order by mes) - 1) * 100 as dolar_cierre_var_m
from mensual
