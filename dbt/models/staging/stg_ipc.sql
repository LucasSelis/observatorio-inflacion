-- Variación mensual del IPC nacional, calculada sobre toda la historia disponible.
select
    cast(fecha as date) as mes,
    valor as ipc_nivel,
    (valor / lag(valor) over (order by fecha) - 1) * 100 as inflacion_m
from {{ source('raw', 'series_raw') }}
where serie = 'ipc'
