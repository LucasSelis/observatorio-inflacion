-- Un mes completo del dólar tiene al menos ~15 días hábiles con dato. Se excluye el mes en curso.
select mes, dias_con_dato
from {{ ref('stg_dolar') }}
where dias_con_dato < 15
  and mes < (select max(mes) from {{ ref('stg_dolar') }})
