select
    cast(fecha as date) as mes,
    valor as reservas_musd
from {{ source('raw', 'series_raw') }}
where serie = 'reservas'
