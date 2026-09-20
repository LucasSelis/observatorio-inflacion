-- La serie es sin desestacionalizar: la variación mensual mezclaría estacionalidad con señal,
-- así que solo se expone la interanual (necesita 12 meses previos, por eso se calcula antes de recortar).
select
    cast(fecha as date) as mes,
    valor as emae_nivel,
    (valor / lag(valor, 12) over (order by fecha) - 1) * 100 as emae_var_a
from {{ source('raw', 'series_raw') }}
where serie = 'emae'
