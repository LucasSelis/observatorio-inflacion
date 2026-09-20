select
    cast(fecha as date) as mes,
    valor as salario_nivel,
    (valor / lag(valor) over (order by fecha) - 1) * 100 as salario_var_m
from {{ source('raw', 'series_raw') }}
where serie = 'salarios'
