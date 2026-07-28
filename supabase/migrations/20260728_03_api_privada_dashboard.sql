begin;

-- ================================================================
-- API privada de lectura para el dashboard Lovable
-- ================================================================
-- Las tablas siguen protegidas por RLS y sin SELECT directo desde el navegador.
-- El frontend autenticado solo puede ejecutar estas funciones controladas:
--   dashboard_resumen  -> KPI, evolución y rankings
--   dashboard_filtros  -> opciones de los selectores
--   dashboard_pedidos  -> explorador paginado, incluidos señalados
--   dashboard_calidad  -> última sincronización y puerta de calidad
--
-- Las funciones usan SECURITY DEFINER para leer las tablas protegidas. Por eso:
--   1. search_path queda vacío;
--   2. todas las tablas se referencian con public.;
--   3. se revoca EXECUTE a public y anon;
--   4. solo authenticated y service_role pueden ejecutarlas.

-- Índices para filtros y ordenación del dashboard.
create index if not exists idx_ventas_clean_fecha
    on public.ventas_clean (fecha);

create index if not exists idx_ventas_clean_fila_origen
    on public.ventas_clean (fila_origen desc);

create index if not exists idx_ventas_clean_comercial
    on public.ventas_clean (comercial);

create index if not exists idx_ventas_clean_zona
    on public.ventas_clean (zona);

create index if not exists idx_ventas_clean_familia
    on public.ventas_clean (familia);

create index if not exists idx_ventas_clean_tipo_cliente
    on public.ventas_clean (tipo_cliente);

create index if not exists idx_ventas_clean_cliente
    on public.ventas_clean (cliente);

-- Reafirmamos que el navegador no puede consultar las tablas directamente.
revoke all on table public.ventas_raw from anon, authenticated;
revoke all on table public.ventas_clean from anon, authenticated;
revoke all on table public.ventas_raw_staging from anon, authenticated;
revoke all on table public.ventas_clean_staging from anon, authenticated;
revoke all on table public.calidad_runs from anon, authenticated;
revoke all on table public.sync_state from anon, authenticated;

-- ================================================================
-- 1. Resumen analítico
-- ================================================================
create or replace function public.dashboard_resumen(
    p_desde date default null,
    p_hasta date default null,
    p_comercial text default null,
    p_zona text default null,
    p_familia text default null,
    p_tipo_cliente text default null
)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
with base_categorias as (
    select v.*
    from public.ventas_clean v
    where not v.sospechoso
      and (p_comercial is null or p_comercial = '' or v.comercial = p_comercial)
      and (p_zona is null or p_zona = '' or v.zona = p_zona)
      and (p_familia is null or p_familia = '' or v.familia = p_familia)
      and (
          p_tipo_cliente is null
          or p_tipo_cliente = ''
          or v.tipo_cliente = p_tipo_cliente
      )
),
limites as (
    select
        min(fecha) as fecha_minima,
        max(fecha) as fecha_maxima,
        coalesce(p_hasta, max(fecha)) as fecha_hasta
    from base_categorias
),
periodo as (
    select
        coalesce(p_desde, (fecha_hasta - interval '12 months')::date) as fecha_desde,
        fecha_hasta,
        fecha_minima,
        fecha_maxima
    from limites
),
actual as (
    select b.*
    from base_categorias b
    cross join periodo p
    where p.fecha_hasta is not null
      and b.fecha >= p.fecha_desde
      and b.fecha <= p.fecha_hasta
),
anterior as (
    select b.*
    from base_categorias b
    cross join periodo p
    where p.fecha_hasta is not null
      and b.fecha >= p.fecha_desde - (p.fecha_hasta - p.fecha_desde)
      and b.fecha < p.fecha_desde
),
kpi_base as (
    select
        coalesce(sum(importe), 0::numeric) as facturacion,
        count(*)::bigint as pedidos,
        coalesce(avg(importe) filter (where not es_devolucion), 0::numeric) as ticket,
        count(distinct cliente)::bigint as clientes,
        coalesce(-sum(importe) filter (where es_devolucion), 0::numeric) as devoluciones,
        coalesce(sum(importe) filter (where not es_devolucion), 0::numeric) as facturacion_bruta
    from actual
),
kpi_anterior as (
    select coalesce(sum(importe), 0::numeric) as facturacion_anterior
    from anterior
),
mensual as (
    select
        to_char(date_trunc('month', fecha), 'YYYY-MM') as mes,
        round(sum(importe), 0) as facturacion,
        count(*)::bigint as pedidos
    from actual
    group by date_trunc('month', fecha)
    order by date_trunc('month', fecha)
),
por_familia as (
    select familia as nombre, round(sum(importe), 0) as importe
    from actual
    group by familia
    order by sum(importe) desc
    limit 8
),
por_producto as (
    select producto as nombre, round(sum(importe), 0) as importe
    from actual
    group by producto
    order by sum(importe) desc
    limit 10
),
por_comercial as (
    select comercial as nombre, round(sum(importe), 0) as importe
    from actual
    group by comercial
    order by sum(importe) desc
    limit 8
),
por_zona as (
    select coalesce(zona, '(sin informar)') as nombre, round(sum(importe), 0) as importe
    from actual
    group by coalesce(zona, '(sin informar)')
    order by sum(importe) desc
    limit 8
),
por_tipo as (
    select tipo_cliente as nombre, round(sum(importe), 0) as importe
    from actual
    group by tipo_cliente
    order by sum(importe) desc
    limit 8
),
por_cliente as (
    select cliente as nombre, round(sum(importe), 0) as importe
    from actual
    group by cliente
    order by sum(importe) desc
    limit 10
)
select jsonb_build_object(
    'kpis', jsonb_build_object(
        'facturacion', round(k.facturacion, 0),
        'var_pct', case
            when a.facturacion_anterior = 0 then null
            else round(((k.facturacion / a.facturacion_anterior) - 1) * 100, 1)
        end,
        'pedidos', k.pedidos,
        'ticket', round(k.ticket, 0),
        'clientes', k.clientes,
        'devoluciones', round(k.devoluciones, 0),
        'dev_pct', case
            when k.facturacion_bruta = 0 then 0
            else round((k.devoluciones / k.facturacion_bruta) * 100, 1)
        end,
        'desde', p.fecha_desde,
        'hasta', p.fecha_hasta
    ),
    'rango_total', jsonb_build_array(p.fecha_minima, p.fecha_maxima),
    'mes', coalesce(
        (select jsonb_agg(to_jsonb(m) order by m.mes) from mensual m),
        '[]'::jsonb
    ),
    'familia', coalesce(
        (select jsonb_agg(to_jsonb(x) order by x.importe desc) from por_familia x),
        '[]'::jsonb
    ),
    'producto', coalesce(
        (select jsonb_agg(to_jsonb(x) order by x.importe desc) from por_producto x),
        '[]'::jsonb
    ),
    'comercial', coalesce(
        (select jsonb_agg(to_jsonb(x) order by x.importe desc) from por_comercial x),
        '[]'::jsonb
    ),
    'zona', coalesce(
        (select jsonb_agg(to_jsonb(x) order by x.importe desc) from por_zona x),
        '[]'::jsonb
    ),
    'tipo', coalesce(
        (select jsonb_agg(to_jsonb(x) order by x.importe desc) from por_tipo x),
        '[]'::jsonb
    ),
    'clientes', coalesce(
        (select jsonb_agg(to_jsonb(x) order by x.importe desc) from por_cliente x),
        '[]'::jsonb
    )
)
from kpi_base k
cross join kpi_anterior a
cross join periodo p;
$$;

-- ================================================================
-- 2. Valores disponibles para los filtros
-- ================================================================
create or replace function public.dashboard_filtros()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
select jsonb_build_object(
    'rango', jsonb_build_array(min(v.fecha), max(v.fecha)),
    'comerciales', coalesce(
        (
            select jsonb_agg(x.valor order by x.valor)
            from (
                select distinct comercial as valor
                from public.ventas_clean
                where not sospechoso and comercial is not null
            ) x
        ),
        '[]'::jsonb
    ),
    'zonas', coalesce(
        (
            select jsonb_agg(x.valor order by x.valor)
            from (
                select distinct zona as valor
                from public.ventas_clean
                where not sospechoso and zona is not null
            ) x
        ),
        '[]'::jsonb
    ),
    'familias', coalesce(
        (
            select jsonb_agg(x.valor order by x.valor)
            from (
                select distinct familia as valor
                from public.ventas_clean
                where not sospechoso and familia is not null
            ) x
        ),
        '[]'::jsonb
    ),
    'tipos_cliente', coalesce(
        (
            select jsonb_agg(x.valor order by x.valor)
            from (
                select distinct tipo_cliente as valor
                from public.ventas_clean
                where not sospechoso and tipo_cliente is not null
            ) x
        ),
        '[]'::jsonb
    )
)
from public.ventas_clean v
where not v.sospechoso;
$$;

-- ================================================================
-- 3. Explorador de pedidos paginado
-- ================================================================
create or replace function public.dashboard_pedidos(
    p_desde date default null,
    p_hasta date default null,
    p_comercial text default null,
    p_zona text default null,
    p_familia text default null,
    p_tipo_cliente text default null,
    p_busqueda text default null,
    p_marca text default null,
    p_orden text default 'fecha',
    p_limite integer default 25,
    p_offset integer default 0
)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
with filtradas as (
    select v.*
    from public.ventas_clean v
    where (p_desde is null or v.fecha >= p_desde)
      and (p_hasta is null or v.fecha <= p_hasta)
      and (p_comercial is null or p_comercial = '' or v.comercial = p_comercial)
      and (p_zona is null or p_zona = '' or v.zona = p_zona)
      and (p_familia is null or p_familia = '' or v.familia = p_familia)
      and (
          p_tipo_cliente is null
          or p_tipo_cliente = ''
          or v.tipo_cliente = p_tipo_cliente
      )
      and (
          p_busqueda is null
          or btrim(p_busqueda) = ''
          or v.cliente ilike '%' || btrim(p_busqueda) || '%'
          or v.producto ilike '%' || btrim(p_busqueda) || '%'
          or v.pedido_id ilike '%' || btrim(p_busqueda) || '%'
          or v.comercial ilike '%' || btrim(p_busqueda) || '%'
      )
      and (
          p_marca is null
          or p_marca = ''
          or (p_marca = 'senalados' and v.sospechoso)
          or (p_marca = 'devoluciones' and v.es_devolucion)
          or (p_marca = 'sin_senalados' and not v.sospechoso)
      )
),
numeradas as (
    select
        f.*,
        row_number() over (
            order by
                case when p_orden = 'registro' then f.fila_origen end desc nulls last,
                case when p_orden <> 'registro' then f.fecha end desc nulls last,
                f.fila_origen desc,
                f.pedido_id desc
        ) as posicion
    from filtradas f
),
pagina as (
    select *
    from numeradas
    order by posicion
    limit least(greatest(coalesce(p_limite, 25), 1), 200)
    offset greatest(coalesce(p_offset, 0), 0)
)
select jsonb_build_object(
    'total', (select count(*) from filtradas),
    'offset', greatest(coalesce(p_offset, 0), 0),
    'limite', least(greatest(coalesce(p_limite, 25), 1), 200),
    'orden', case when p_orden = 'registro' then 'registro' else 'fecha' end,
    'importe', coalesce((select round(sum(importe), 0) from filtradas), 0),
    'filas', coalesce(
        (
            select jsonb_agg(
                jsonb_build_object(
                    'pedido_id', pedido_id,
                    'fecha', fecha,
                    'comercial', comercial,
                    'zona', zona,
                    'cliente', cliente,
                    'tipo_cliente', tipo_cliente,
                    'producto', producto,
                    'familia', familia,
                    'cantidad', cantidad,
                    'precio', precio_unitario,
                    'importe', importe,
                    'devolucion', es_devolucion,
                    'senalado', sospechoso,
                    'fila_origen', fila_origen
                )
                order by posicion
            )
            from pagina
        ),
        '[]'::jsonb
    )
);
$$;

-- ================================================================
-- 4. Estado de la sincronización y última puerta de calidad
-- ================================================================
create or replace function public.dashboard_calidad()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
select jsonb_build_object(
    'sync', coalesce(
        (
            select jsonb_build_object(
                'estado', s.ultimo_estado,
                'ultima_sincronizacion', s.ultima_sincronizacion,
                'ultima_comprobacion', s.ultima_comprobacion,
                'version_puerta', s.version_puerta,
                'filas_crudas', s.filas_crudas,
                'filas_limpias', s.filas_limpias,
                'ultimo_error', s.ultimo_error
            )
            from public.sync_state s
            where s.dataset_key = 'ventas'
            limit 1
        ),
        '{}'::jsonb
    ),
    'calidad', coalesce(
        (
            select jsonb_build_object(
                'id', c.id,
                'estado', c.estado,
                'origen', c.origen,
                'started_at', c.started_at,
                'finished_at', c.finished_at,
                'filas_crudas', c.filas_crudas,
                'filas_limpias', c.filas_limpias,
                'facturacion_cruda', c.facturacion_cruda,
                'facturacion_limpia', c.facturacion_limpia,
                'incidencias', c.incidencias,
                'mensaje', c.mensaje,
                'version_puerta', c.version_puerta
            )
            from public.calidad_runs c
            order by c.created_at desc
            limit 1
        ),
        '{}'::jsonb
    )
);
$$;

-- Las funciones no quedan abiertas por defecto.
revoke execute on function public.dashboard_resumen(date, date, text, text, text, text)
from public, anon;
revoke execute on function public.dashboard_filtros()
from public, anon;
revoke execute on function public.dashboard_pedidos(
    date, date, text, text, text, text, text, text, text, integer, integer
)
from public, anon;
revoke execute on function public.dashboard_calidad()
from public, anon;

-- Solo una sesión autenticada de Supabase o el backend seguro puede leer.
grant execute on function public.dashboard_resumen(date, date, text, text, text, text)
to authenticated, service_role;
grant execute on function public.dashboard_filtros()
to authenticated, service_role;
grant execute on function public.dashboard_pedidos(
    date, date, text, text, text, text, text, text, text, integer, integer
)
to authenticated, service_role;
grant execute on function public.dashboard_calidad()
to authenticated, service_role;

commit;
