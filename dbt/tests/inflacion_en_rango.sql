-- Una inflación mensual fuera de -5%..50% casi seguro es un error de carga, no un dato.
select mes, inflacion_m
from {{ ref('stg_ipc') }}
where inflacion_m is not null
  and inflacion_m not between -5 and 50
