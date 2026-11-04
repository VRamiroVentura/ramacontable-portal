-- Ramacontable · base de datos del portal
-- Se pega UNA vez en Supabase → SQL Editor → New query → Run.
-- Se puede volver a correr sin romper nada.

-- ===== Perfiles (públicos: nombre y tipo) =====
create table if not exists public.perfiles (
  id uuid primary key references auth.users(id) on delete cascade,
  nombre text not null check (char_length(nombre) between 2 and 60),
  tipo text not null check (tipo in ('recibido','estudiante','otro')),
  avance int check (avance between 0 and 100),
  creado timestamptz not null default now()
);

-- ===== Preferencias (privadas: solo las ve cada uno) =====
create table if not exists public.preferencias (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  newsletter boolean not null default false,
  actualizado timestamptz not null default now()
);

-- ===== Paso a paso (contenido pegado o convertido: texto, tablas e imágenes) =====
create table if not exists public.pasos (
  id bigint generated always as identity primary key,
  nota text not null,
  autor uuid not null default auth.uid() references public.perfiles(id) on delete cascade,
  titulo text not null check (char_length(titulo) between 5 and 140),
  nivel text not null check (nivel in ('basico','intermedio','avanzado')),
  contenido text not null check (char_length(contenido) between 10 and 200000),
  porque text not null check (char_length(porque) between 20 and 2000),
  sin_datos_reales boolean not null check (sin_datos_reales),
  texto_pdf text check (char_length(texto_pdf) <= 60000),
  oculto boolean not null default false,
  creado timestamptz not null default now()
);
alter table public.pasos add column if not exists texto_pdf text check (char_length(texto_pdf) <= 60000);
create index if not exists pasos_nota on public.pasos(nota);

-- ===== Opiniones =====
create table if not exists public.opiniones (
  id bigint generated always as identity primary key,
  nota text not null,
  autor uuid not null default auth.uid() references public.perfiles(id) on delete cascade,
  texto text not null check (char_length(texto) between 2 and 1500),
  oculto boolean not null default false,
  creado timestamptz not null default now()
);
create index if not exists opiniones_nota on public.opiniones(nota);
alter table public.pasos add column if not exists editado timestamptz;
alter table public.opiniones add column if not exists editado timestamptz;

-- ===== Votos =====
create table if not exists public.votos (
  id bigint generated always as identity primary key,
  autor uuid not null default auth.uid() references public.perfiles(id) on delete cascade,
  objeto text not null check (objeto in ('paso','opinion')),
  objeto_id bigint not null,
  valor text not null check (valor in ('like','sirvio','neg')),
  motivo text check (char_length(motivo) <= 300),
  creado timestamptz not null default now(),
  unique (autor, objeto, objeto_id, valor),
  check (valor <> 'neg' or char_length(coalesce(motivo,'')) >= 5)
);
create index if not exists votos_obj on public.votos(objeto, objeto_id);

-- ===== Filtro de reglas: sin mails, teléfonos, CUIT/CBU, redes ni links no oficiales =====
create or replace function public.revisar_texto(t text) returns void
language plpgsql immutable as $$
declare
  m text[];
  host text;
begin
  if t is null then return; end if;
  if t ~* '[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}' then
    raise exception 'REGLA: No se pueden publicar direcciones de mail.';
  end if;
  if t ~* '(^|[^a-z0-9])@[a-z0-9_.]{3,}' then
    raise exception 'REGLA: No se pueden publicar usuarios de redes sociales.';
  end if;
  if t ~* '(whats ?app|wsp|wpp|instagram|telegram|facebook|linkedin|tiktok|wa\.me)' then
    raise exception 'REGLA: No se pueden publicar redes sociales ni medios de contacto.';
  end if;
  if t ~ '\d{10,}' or t ~ '\m\d{2}-\d{8}-\d\M' or t ~ '\m\d{2,4}[ -]\d{3,4}[ -]\d{4}\M' then
    raise exception 'REGLA: No se pueden publicar teléfonos, CUIT, DNI ni cuentas bancarias.';
  end if;
  for m in select regexp_matches(t, '(?:https?://)?(?:www\.)?((?:[a-z0-9-]+\.)+(?:com|net|org|ar|io|me|ly|info|co|app|xyz|site|online|store|link|gob|gov)(?:\.ar)?)(?![a-z0-9])', 'gi') loop
    host := lower(m[1]);
    if not (host ~ '\.(gob|gov)\.ar$' or host in ('consejo.org.ar','cpba.com.ar','facpce.org.ar')) then
      raise exception 'REGLA: Solo se permiten links de organismos oficiales (.gob.ar / .gov.ar) y consejos profesionales.';
    end if;
  end loop;
end $$;

create or replace function public.filtrar_aporte() returns trigger
language plpgsql as $$
begin
  if tg_op = 'UPDATE' and tg_table_name in ('pasos','opiniones') then
    if new.nota <> old.nota or new.autor <> old.autor or new.creado <> old.creado or new.oculto <> old.oculto then
      raise exception 'REGLA: Solo se puede modificar el contenido.';
    end if;
    new.editado := now();
  end if;
  if tg_table_name = 'opiniones' then
    perform public.revisar_texto(new.texto);
  elsif tg_table_name = 'pasos' then
    if new.contenido ~* '<\s*/?\s*(script|iframe|object|embed|form|input|button|link|meta|style|svg|math|base)' or new.contenido ~* '\son[a-z]+\s*=' or new.contenido ~* 'javascript:' or new.contenido ~* '<a[\s>]' then
      raise exception 'REGLA: El contenido tiene elementos no permitidos.';
    end if;
    if new.contenido ~* 'src\s*=\s*"(?!https://[a-z0-9]+\.supabase\.co/storage/v1/object/public/pasos/)' then
      raise exception 'REGLA: Solo se permiten imágenes subidas al portal.';
    end if;
    perform public.revisar_texto(new.titulo || ' ' || new.porque || ' ' || regexp_replace(new.contenido, '<[^>]*>', ' ', 'g') || ' ' || coalesce(new.texto_pdf, ''));
  elsif tg_table_name = 'votos' then
    perform public.revisar_texto(new.motivo);
    if (new.objeto = 'paso' and exists (select 1 from public.pasos where id = new.objeto_id and autor = new.autor))
       or (new.objeto = 'opinion' and exists (select 1 from public.opiniones where id = new.objeto_id and autor = new.autor)) then
      raise exception 'REGLA: No podés votar tus propios aportes.';
    end if;
  elsif tg_table_name = 'perfiles' then
    perform public.revisar_texto(new.nombre);
  end if;
  return new;
end $$;

drop trigger if exists filtro on public.opiniones;
create trigger filtro before insert or update on public.opiniones for each row execute function public.filtrar_aporte();
drop trigger if exists filtro on public.pasos;
create trigger filtro before insert or update on public.pasos for each row execute function public.filtrar_aporte();
drop trigger if exists filtro on public.votos;
create trigger filtro before insert or update on public.votos for each row execute function public.filtrar_aporte();
drop trigger if exists filtro on public.perfiles;
create trigger filtro before insert or update on public.perfiles for each row execute function public.filtrar_aporte();

-- ===== Reputación: votos recibidos por cada usuario =====
create or replace view public.reputacion with (security_invoker = true) as
select p.id as usuario, p.nombre, p.tipo,
  coalesce(sum(case when v.valor in ('like','sirvio') then 1 else 0 end),0)::int as positivos,
  coalesce(sum(case when v.valor = 'neg' then 1 else 0 end),0)::int as negativos,
  ((select count(*) from public.pasos x where x.autor = p.id and not x.oculto)
   + (select count(*) from public.opiniones y where y.autor = p.id and not y.oculto))::int as aportes
from public.perfiles p
left join (
  select v.valor, coalesce(pa.autor, op.autor) as duenio
  from public.votos v
  left join public.pasos pa on v.objeto = 'paso' and pa.id = v.objeto_id and not pa.oculto
  left join public.opiniones op on v.objeto = 'opinion' and op.id = v.objeto_id and not op.oculto
) v on v.duenio = p.id
group by p.id, p.nombre, p.tipo;

-- ===== Seguridad (RLS) =====
alter table public.perfiles enable row level security;
alter table public.preferencias enable row level security;
alter table public.pasos enable row level security;
alter table public.opiniones enable row level security;
alter table public.votos enable row level security;

drop policy if exists "ver perfiles" on public.perfiles;
create policy "ver perfiles" on public.perfiles for select using (true);
drop policy if exists "crear mi perfil" on public.perfiles;
create policy "crear mi perfil" on public.perfiles for insert to authenticated with check (id = auth.uid());
drop policy if exists "editar mi perfil" on public.perfiles;
create policy "editar mi perfil" on public.perfiles for update to authenticated using (id = auth.uid()) with check (id = auth.uid());

drop policy if exists "mis preferencias" on public.preferencias;
create policy "mis preferencias" on public.preferencias for all to authenticated using (id = auth.uid()) with check (id = auth.uid());

drop policy if exists "ver pasos" on public.pasos;
create policy "ver pasos" on public.pasos for select using (not oculto);
drop policy if exists "subir paso" on public.pasos;
create policy "subir paso" on public.pasos for insert to authenticated with check (autor = auth.uid() and oculto = false);
drop policy if exists "borrar mi paso" on public.pasos;
create policy "borrar mi paso" on public.pasos for delete to authenticated using (autor = auth.uid());
drop policy if exists "editar mi paso" on public.pasos;
create policy "editar mi paso" on public.pasos for update to authenticated using (autor = auth.uid()) with check (autor = auth.uid());

drop policy if exists "ver opiniones" on public.opiniones;
create policy "ver opiniones" on public.opiniones for select using (not oculto);
drop policy if exists "opinar" on public.opiniones;
create policy "opinar" on public.opiniones for insert to authenticated with check (autor = auth.uid() and oculto = false);
drop policy if exists "borrar mi opinion" on public.opiniones;
create policy "borrar mi opinion" on public.opiniones for delete to authenticated using (autor = auth.uid());
drop policy if exists "editar mi opinion" on public.opiniones;
create policy "editar mi opinion" on public.opiniones for update to authenticated using (autor = auth.uid()) with check (autor = auth.uid());

drop policy if exists "ver votos" on public.votos;
create policy "ver votos" on public.votos for select using (true);
drop policy if exists "votar" on public.votos;
create policy "votar" on public.votos for insert to authenticated with check (autor = auth.uid());
drop policy if exists "sacar mi voto" on public.votos;
create policy "sacar mi voto" on public.votos for delete to authenticated using (autor = auth.uid());

grant select on public.reputacion to anon, authenticated;

-- ===== Imágenes de los paso a paso (capturas y páginas de PDF ya convertidas) =====
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('pasos', 'pasos', true, 1048576, array['image/jpeg','image/png','image/webp'])
on conflict (id) do update set public = true, file_size_limit = 1048576, allowed_mime_types = array['image/jpeg','image/png','image/webp'];

drop policy if exists "subir mis imagenes" on storage.objects;
create policy "subir mis imagenes" on storage.objects for insert to authenticated
  with check (bucket_id = 'pasos' and (storage.foldername(name))[1] = auth.uid()::text);

-- =====================================================================
-- ===== Notas del portal, administradores y radar de la fábrica =====
-- =====================================================================
create table if not exists public.admins (email text primary key);
insert into public.admins(email) values ('ramacontable@gmail.com'), ('rventrura95@gmail.com') on conflict do nothing;
alter table public.admins enable row level security;

create or replace function public.es_admin() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.admins where email = lower(coalesce(auth.jwt() ->> 'email', '')));
$$;
grant execute on function public.es_admin() to anon, authenticated;

create table if not exists public.notas (
  slug text primary key check (slug ~ '^[a-z0-9-]{3,90}$'),
  fecha date not null default current_date,
  seccion text not null check (seccion in ('sueldos','impuestos','profesion','economia')),
  antetitulo text not null default '',
  titulo text not null check (char_length(titulo) between 5 and 200),
  dato text,
  encorto text not null default '',
  cuerpo jsonb not null default '[]'::jsonb,
  fuente text not null default '',
  fuentes jsonb not null default '[]'::jsonb,
  verificada boolean not null default false,
  estado text not null default 'publicada' check (estado in ('publicada','revision','borrada')),
  tema text,
  actualiza text,
  motivo_revision text,
  creado timestamptz not null default now(),
  actualizado timestamptz not null default now(),
  editado_por text
);
create index if not exists notas_fecha on public.notas(fecha desc);

create or replace function public.tocar_nota() returns trigger language plpgsql as $$
begin
  new.actualizado := now();
  if auth.uid() is not null then new.editado_por := auth.jwt() ->> 'email'; end if;
  return new;
end $$;
drop trigger if exists tocar on public.notas;
create trigger tocar before update on public.notas for each row execute function public.tocar_nota();

alter table public.notas enable row level security;
drop policy if exists "ver notas" on public.notas;
create policy "ver notas" on public.notas for select using (estado = 'publicada' or public.es_admin());
drop policy if exists "admin edita notas" on public.notas;
create policy "admin edita notas" on public.notas for update to authenticated using (public.es_admin()) with check (public.es_admin());
drop policy if exists "admin borra notas" on public.notas;
create policy "admin borra notas" on public.notas for delete to authenticated using (public.es_admin());

-- El administrador puede moderar aportes de la comunidad
drop policy if exists "admin borra pasos" on public.pasos;
create policy "admin borra pasos" on public.pasos for delete to authenticated using (public.es_admin());
drop policy if exists "admin borra opiniones" on public.opiniones;
create policy "admin borra opiniones" on public.opiniones for delete to authenticated using (public.es_admin());

-- Memoria del radar (solo la usa la fábrica con la clave secreta; nadie la ve desde la web)
create table if not exists public.radar (
  url text primary key,
  fuente text not null,
  tipo text not null default 'portal',
  titulo text not null,
  texto text,
  fecha timestamptz,
  visto timestamptz not null default now(),
  usado boolean not null default false,
  tema text,
  nota text
);
alter table public.radar enable row level security;

-- Slugs que existen pero no están publicados (para que la web no muestre notas retiradas)
create or replace function public.slugs_no_publicados() returns setof text
language sql stable security definer set search_path = public as $$
  select slug from public.notas where estado <> 'publicada';
$$;
grant execute on function public.slugs_no_publicados() to anon, authenticated;

-- Datos para buscadores (Google)
alter table public.notas add column if not exists seo_titulo text;
alter table public.notas add column if not exists descripcion_seo text;
alter table public.notas add column if not exists preguntas jsonb not null default '[]'::jsonb;

-- ===== Convenios y escalas salariales =====
create table if not exists public.convenios (
  slug text primary key check (slug ~ '^[a-z0-9-]{2,60}$'),
  nombre text not null,
  cct text not null default '',
  partes text not null default '',
  descripcion text not null default '',
  escala jsonb,              -- {"periodo": "...", "vigencia": "...", "tabla": [[...],[...]], "aclaraciones": "..."}
  novedades jsonb not null default '[]'::jsonb,   -- bloques {h|p|tabla|html}
  calculo jsonb not null default '[]'::jsonb,
  nr jsonb not null default '[]'::jsonb,
  recibo jsonb not null default '[]'::jsonb,
  preguntas jsonb not null default '[]'::jsonb,
  historial jsonb not null default '[]'::jsonb,   -- [{"periodo","fecha","nota"}]
  fuente text not null default '',
  propuesta jsonb,           -- actualización que la fábrica no pudo verificar (espera al administrador)
  motivo_propuesta text,
  actualizado timestamptz not null default now(),
  editado_por text
);
drop trigger if exists tocar on public.convenios;
create trigger tocar before update on public.convenios for each row execute function public.tocar_nota();
alter table public.convenios enable row level security;
drop policy if exists "ver convenios" on public.convenios;
create policy "ver convenios" on public.convenios for select using (true);
drop policy if exists "admin edita convenios" on public.convenios;
create policy "admin edita convenios" on public.convenios for update to authenticated using (public.es_admin()) with check (public.es_admin());
alter table public.notas add column if not exists convenio text;

-- ===== v5: guías prácticas (se guardan como notas de tipo 'guia') =====
alter table public.notas add column if not exists tipo text not null default 'nota';
do $$ begin
  alter table public.notas add constraint notas_tipo_ok check (tipo in ('nota','guia'));
exception when duplicate_object then null; end $$;
create index if not exists notas_tipo on public.notas(tipo);

-- ===== v13: agenda de vencimientos y feriados (la arma la fábrica con lo que publican los portales) =====
create table if not exists public.vencimientos (
  mes text primary key check (mes ~ '^\d{4}-\d{2}$'),
  items jsonb not null default '[]'::jsonb,
  feriados jsonb not null default '[]'::jsonb,
  fuentes jsonb not null default '[]'::jsonb,
  actualizado timestamptz not null default now()
);
alter table public.vencimientos enable row level security;
drop policy if exists "todos leen vencimientos" on public.vencimientos;
create policy "todos leen vencimientos" on public.vencimientos for select using (true);

-- ===== v19: contador de visitas propio (sin cookies ni servicios externos) =====
create table if not exists public.visitas (
  dia date not null default current_date,
  ruta text not null check (char_length(ruta) <= 120),
  vistas int not null default 0,
  visitantes int not null default 0,
  primary key (dia, ruta)
);
create table if not exists public.visitas_origen (
  dia date not null default current_date,
  origen text not null check (char_length(origen) <= 60),
  n int not null default 0,
  primary key (dia, origen)
);
alter table public.visitas enable row level security;
alter table public.visitas_origen enable row level security;
drop policy if exists "admin ve visitas" on public.visitas;
create policy "admin ve visitas" on public.visitas for select to authenticated using (public.es_admin());
drop policy if exists "admin ve origenes" on public.visitas_origen;
create policy "admin ve origenes" on public.visitas_origen for select to authenticated using (public.es_admin());

-- La web solo puede sumar 1 visita por llamada (no puede leer ni borrar nada)
create or replace function public.sumar_visita(p_ruta text, p_nuevo boolean, p_origen text)
returns void language plpgsql security definer set search_path = public as $$
declare
  r text := left(regexp_replace(coalesce(p_ruta, ''), '[^a-z0-9._/-]', '', 'gi'), 120);
  o text := left(regexp_replace(lower(coalesce(p_origen, '')), '[^a-z0-9.-]', '', 'g'), 60);
  hoy date := (now() at time zone 'America/Argentina/Buenos_Aires')::date;
begin
  if r = '' then r := 'index.html'; end if;
  insert into public.visitas(dia, ruta, vistas, visitantes) values (hoy, r, 1, case when p_nuevo then 1 else 0 end)
  on conflict (dia, ruta) do update set vistas = visitas.vistas + 1, visitantes = visitas.visitantes + case when p_nuevo then 1 else 0 end;
  if o <> '' then
    insert into public.visitas_origen(dia, origen, n) values (hoy, o, 1)
    on conflict (dia, origen) do update set n = visitas_origen.n + 1;
  end if;
end $$;
revoke all on function public.sumar_visita(text, boolean, text) from public;
grant execute on function public.sumar_visita(text, boolean, text) to anon, authenticated;

-- ===== v23: frase clave de cada nota (lo que la tarjeta muestra y no está en el título) =====
alter table public.notas add column if not exists clave text check (char_length(clave) <= 120);
