-- Una fila por mes con IPC publicado. Las demás series entran con left join:
-- si todavía no se publicaron (salarios y EMAE llegan con ~2 meses de demora) quedan en null.
select
    i.mes,
    i.ipc_nivel,
    i.inflacion_m,
    d.dolar_prom,
    d.dolar_var_m,
    d.dolar_cierre_var_m,
    s.salario_var_m,
    e.emae_var_a,
    r.reservas_musd
from {{ ref('stg_ipc') }} as i
left join {{ ref('stg_dolar') }} as d using (mes)
left join {{ ref('stg_salarios') }} as s using (mes)
left join {{ ref('stg_emae') }} as e using (mes)
left join {{ ref('stg_reservas') }} as r using (mes)
order by i.mes
