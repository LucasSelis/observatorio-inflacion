-- Falla si falta algún mes en el IPC (cada fila debe estar exactamente un mes después de la anterior).
select mes, mes_anterior
from (
    select mes, lag(mes) over (order by mes) as mes_anterior
    from {{ ref('stg_ipc') }}
)
where mes_anterior is not null
  and mes <> mes_anterior + interval 1 month
