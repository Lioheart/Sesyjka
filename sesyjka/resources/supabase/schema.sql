-- Sesyjka Cloud 0.9.6
-- Uruchom ten plik jeden raz w Supabase SQL Editor.

create table if not exists public.sesyjka_records (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
    entity_type text not null,
    record_key text not null,
    payload jsonb not null default '{}'::jsonb,
    version bigint not null default 1 check (version > 0),
    deleted boolean not null default false,
    device_id text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (owner_id, entity_type, record_key)
);

create index if not exists sesyjka_records_owner_updated_idx
    on public.sesyjka_records(owner_id, updated_at desc);

alter table public.sesyjka_records enable row level security;

revoke all on table public.sesyjka_records from anon;
grant select, insert, update, delete on table public.sesyjka_records to authenticated;

drop policy if exists "sesyjka_select_own" on public.sesyjka_records;
create policy "sesyjka_select_own"
on public.sesyjka_records
for select
to authenticated
using ((select auth.uid()) = owner_id);

drop policy if exists "sesyjka_insert_own" on public.sesyjka_records;
create policy "sesyjka_insert_own"
on public.sesyjka_records
for insert
to authenticated
with check ((select auth.uid()) = owner_id);

drop policy if exists "sesyjka_update_own" on public.sesyjka_records;
create policy "sesyjka_update_own"
on public.sesyjka_records
for update
to authenticated
using ((select auth.uid()) = owner_id)
with check ((select auth.uid()) = owner_id);

drop policy if exists "sesyjka_delete_own" on public.sesyjka_records;
create policy "sesyjka_delete_own"
on public.sesyjka_records
for delete
to authenticated
using ((select auth.uid()) = owner_id);

create or replace function public.sesyjka_touch_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = public
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists sesyjka_records_touch_updated_at on public.sesyjka_records;
create trigger sesyjka_records_touch_updated_at
before update on public.sesyjka_records
for each row execute function public.sesyjka_touch_updated_at();

-- Odśwież cache schematu Data API po wdrożeniu.
NOTIFY pgrst, 'reload schema';
