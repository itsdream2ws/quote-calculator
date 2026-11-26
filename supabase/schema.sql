-- Quote Calculator database (Supabase / Postgres).
-- Already applied to the live project. Kept here so the database can be rebuilt
-- from scratch: paste into Supabase > SQL Editor > New query > Run.

-- Who may use the app: any signed-in, non-anonymous user. Public sign-ups are
-- switched off in Supabase, so the only accounts are the ones the owner adds.
create or replace function public.is_staff()
returns boolean
language sql stable
set search_path = ''
as $$
  select auth.uid() is not null
     and coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false) = false
$$;

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end
$$;

-- Price list: tickets (looked up by code on the quote page)
create table public.tickets (
  code         text primary key check (code <> '' and code = upper(code)),
  name         text not null,
  supplier     text not null,
  adult_price  numeric(12,2) not null check (adult_price >= 0),
  child_price  numeric(12,2) not null check (child_price >= 0),
  valid_until  date not null,
  confirmed_at date,
  updated_at   timestamptz not null default now()
);

-- Price list: standard transport items
create table public.transport_items (
  id         text primary key,
  name       text not null,
  supplier   text not null,
  price      numeric(12,2) not null check (price >= 0),
  updated_at timestamptz not null default now(),
  -- Typed in the quote page's code bar, like a ticket code. Optional for older items.
  code       text unique check (code is null or (code <> '' and code = upper(code)))
);

-- Price list: guides, each for a place or attraction (e.g. a guide for Universal Studios)
create table public.guide_items (
  id         text primary key,
  code       text not null unique check (code <> '' and code = upper(code)),
  name       text not null,
  supplier   text not null,
  price      numeric(12,2) not null check (price >= 0),
  updated_at timestamptz not null default now()
);

-- Saved quotes. `data` holds the whole quote exactly as the app builds it
-- (days, hotels, flat tickets/transport copies, totals; see DATA_FORMAT.md).
-- The columns beside it are copies for sorting, searching and uniqueness.
create table public.quotes (
  id           text primary key,
  quote_number text not null unique,
  quote_date   date not null,
  client_name  text not null,
  total        numeric(12,2) not null default 0,
  data         jsonb not null,
  created_by   uuid default auth.uid() references auth.users (id) on delete set null,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index quotes_quote_date_idx on public.quotes (quote_date);
create index quotes_created_by_idx on public.quotes (created_by);

-- App settings: a single row (id = 1)
create table public.settings (
  id         smallint primary key default 1 check (id = 1),
  data       jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create trigger tickets_touch before update on public.tickets for each row execute function public.touch_updated_at();
create trigger transport_items_touch before update on public.transport_items for each row execute function public.touch_updated_at();
create trigger guide_items_touch before update on public.guide_items for each row execute function public.touch_updated_at();
create trigger quotes_touch before update on public.quotes for each row execute function public.touch_updated_at();
create trigger settings_touch before update on public.settings for each row execute function public.touch_updated_at();

-- Row level security: nothing can be read or written without signing in.
alter table public.tickets enable row level security;
alter table public.transport_items enable row level security;
alter table public.guide_items enable row level security;
alter table public.quotes enable row level security;
alter table public.settings enable row level security;

create policy "staff full access" on public.tickets for all to authenticated using ((select public.is_staff())) with check ((select public.is_staff()));
create policy "staff full access" on public.transport_items for all to authenticated using ((select public.is_staff())) with check ((select public.is_staff()));
create policy "staff full access" on public.guide_items for all to authenticated using ((select public.is_staff())) with check ((select public.is_staff()));
create policy "staff full access" on public.quotes for all to authenticated using ((select public.is_staff())) with check ((select public.is_staff()));
create policy "staff full access" on public.settings for all to authenticated using ((select public.is_staff())) with check ((select public.is_staff()));

-- Signed-in users may use the tables (row level security above still applies).
-- Logged-out visitors (the "anon" role) get no table access at all.
grant select, insert, update, delete on public.tickets, public.transport_items, public.guide_items, public.quotes, public.settings to authenticated;
revoke all on public.tickets, public.transport_items, public.guide_items, public.quotes, public.settings from anon;
revoke execute on function public.is_staff() from anon, public;
grant execute on function public.is_staff() to authenticated;
revoke execute on function public.touch_updated_at() from anon, authenticated, public;

-- Every ticket, transport, meal, guide, hotel and group additional-charge line on saved quotes
-- with its travel date, for checking supplier invoices straight from Supabase > Table Editor.
-- security_invoker makes the view obey the same row level security.
create or replace view public.supplier_lines with (security_invoker = true) as
  select q.quote_number, q.quote_date, q.client_name,
         nullif(coalesce(l->>'travelDate', l->>'date'), '')::date as travel_date,
         'ticket'::text as line_type, l->>'code' as code, l->>'name' as item, l->>'supplier' as supplier,
         coalesce((l->>'pax')::numeric, 0) as qty, (l->>'adults')::numeric as adults, (l->>'children')::numeric as children,
         (l->>'adultPrice')::numeric as adult_price, (l->>'childPrice')::numeric as child_price,
         coalesce((l->>'total')::numeric, (l->>'pax')::numeric * (l->>'unitPrice')::numeric) as total
    from public.quotes q
    cross join lateral jsonb_array_elements(coalesce(q.data->'tickets', '[]'::jsonb)) l
  union all
  select q.quote_number, q.quote_date, q.client_name,
         nullif(coalesce(l->>'travelDate', l->>'date'), '')::date,
         'transport', nullif(l->>'code', ''), l->>'description', l->>'supplier',
         coalesce((l->>'qty')::numeric, 0), null, null, (l->>'unitPrice')::numeric, null,
         coalesce((l->>'total')::numeric, (l->>'qty')::numeric * (l->>'unitPrice')::numeric)
    from public.quotes q
    cross join lateral jsonb_array_elements(coalesce(q.data->'transport', '[]'::jsonb)) l
  union all
  select q.quote_number, q.quote_date, q.client_name,
         nullif(l->>'travelDate', '')::date,
         'meal', null, concat_ws(' — ', l->>'meal', nullif(l->>'description', '')), l->>'supplier',
         coalesce((l->>'pax')::numeric, 0), (l->>'adults')::numeric, (l->>'children')::numeric,
         (l->>'adultPrice')::numeric, (l->>'childPrice')::numeric, (l->>'total')::numeric
    from public.quotes q
    cross join lateral jsonb_array_elements(coalesce(q.data->'meals', '[]'::jsonb)) l
  union all
  select q.quote_number, q.quote_date, q.client_name,
         nullif(l->>'travelDate', '')::date,
         'guide', nullif(l->>'code', ''), concat_ws(' — ', 'Guide', nullif(l->>'description', '')), l->>'supplier',
         coalesce((l->>'qty')::numeric, 0), null, null, (l->>'unitPrice')::numeric, null, (l->>'total')::numeric
    from public.quotes q
    cross join lateral jsonb_array_elements(coalesce(q.data->'guides', '[]'::jsonb)) l
  union all
  -- Hotels and group additional charges have no date of their own: listed under the first day of the trip.
  select q.quote_number, q.quote_date, q.client_name,
         (select min(nullif(d->>'date', '')::date) from jsonb_array_elements(coalesce(q.data->'days', '[]'::jsonb)) d),
         'hotel', null, l->>'description', nullif(l->>'supplier', ''),
         1, null, null, (l->>'amount')::numeric, null, (l->>'amount')::numeric
    from public.quotes q
    cross join lateral jsonb_array_elements(coalesce(q.data->'hotels', '[]'::jsonb)) l
  union all
  select q.quote_number, q.quote_date, q.client_name,
         (select min(nullif(d->>'date', '')::date) from jsonb_array_elements(coalesce(q.data->'days', '[]'::jsonb)) d),
         'additional', null, l->>'description', nullif(l->>'supplier', ''),
         1, null, null, (l->>'amount')::numeric, null, (l->>'amount')::numeric
    from public.quotes q
    cross join lateral jsonb_array_elements(case when q.data->>'quoteType' = 'group' then coalesce(q.data->'additionalCharges', '[]'::jsonb) else '[]'::jsonb end) l;

grant select on public.supplier_lines to authenticated;
revoke all on public.supplier_lines from anon;
