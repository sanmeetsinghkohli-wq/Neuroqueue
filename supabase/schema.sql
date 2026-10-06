-- NeuroQueue schema for the Supabase project "brain2".
-- Run once in the SQL editor (or apply as a migration). Safe to re-run.
--
-- The FastAPI backend is the only client of this database. Row-level security is
-- on for every table and nothing is readable with the anon key. The backend
-- connects either with the service-role key (bypasses RLS) or as the dedicated
-- service account from service_account.sql (allowed by the policies below).

create table if not exists public.users (
  id uuid primary key,
  email text not null unique,
  password_hash text,                         -- scrypt hash; null for Google-only accounts
  email_verified boolean not null default false,
  google_sub text unique,
  session_version integer not null default 0,  -- bumping it ends every session for the account
  full_name text not null,
  role text not null check (role in ('patient', 'doctor', 'admin')),
  status text not null check (status in ('pending', 'approved', 'rejected', 'disabled')),
  phone text, specialty text, license_no text, hospital text, date_of_birth text, gender text,
  created_at timestamptz not null default now(),
  approved_at timestamptz, approved_by_name text
);

create table if not exists public.scans (
  id uuid primary key,
  filename text not null,
  storage_path text not null,
  content_type text,
  heatmap_path text,
  patient_id uuid references public.users(id) on delete set null,
  patient_name text,
  uploaded_by uuid references public.users(id) on delete set null,
  uploaded_by_name text,
  uploaded_at timestamptz not null default now(),
  -- an administrator uploads the scan and assigns the doctor who will read it; only that doctor can open it
  assigned_doctor_id uuid references public.users(id) on delete set null,
  assigned_doctor_name text,
  assigned_at timestamptz,
  -- there is deliberately no "cleared" status: every scan ends at a radiologist's signature
  status text not null check (status in ('pending', 'processing', 'classified', 'reviewed', 'drafted', 'signed', 'failed')),
  tier text check (tier in ('URGENT', 'REVIEW', 'ROUTINE')),
  tier_provisional boolean not null default false,
  reasons jsonb not null default '[]', notes jsonb not null default '[]',
  prediction jsonb, ood jsonb, verifier jsonb,   -- prediction is the trained model's output and is never edited
  classified_at timestamptz, escalated_at timestamptz,
  review jsonb, reviewed_at timestamptz,
  report_id uuid, signed_at timestamptz, error text,
  is_demo boolean not null default false, demo_true_label text,
  exam_type text default 'MRI Brain', clinical_concern text, referring_doctor text, patient_age integer, patient_gender text
);
create index if not exists scans_status_idx on public.scans (status);
create index if not exists scans_patient_idx on public.scans (patient_id);
create index if not exists scans_assigned_doctor_idx on public.scans (assigned_doctor_id);
create index if not exists scans_uploaded_idx on public.scans (uploaded_at);

create table if not exists public.reports (
  id uuid primary key,
  report_no text unique,
  scan_id uuid not null references public.scans(id) on delete cascade,
  status text not null check (status in ('passed', 'blocked', 'signed')),
  clinical_text text not null, patient_summary text not null,
  "check" jsonb not null, sources jsonb, guard jsonb,
  created_at timestamptz not null default now(), updated_at timestamptz,
  signed_by uuid, signed_by_name text, signed_at timestamptz,
  pdf_path text,            -- clinical version (doctors)
  patient_pdf_path text     -- plain-language version (the only one a patient can download)
);

-- Append-only, hash-chained audit log. `ts` is text so the hashed value never changes shape.
create table if not exists public.audit_events (
  seq bigint generated always as identity primary key,
  id uuid not null unique,
  ts text not null,
  actor_id text, actor_name text,
  action text not null,
  scan_id text,
  details jsonb not null default '{}',
  prev_hash text not null,
  hash text not null
);
create index if not exists audit_scan_idx on public.audit_events (scan_id);

-- One-time tokens for email verification and password reset. Only the hash is stored.
create table if not exists public.auth_tokens (
  id uuid primary key,
  user_id uuid not null references public.users(id) on delete cascade,
  kind text not null check (kind in ('verify_email', 'reset_password')),
  token_hash text not null unique,
  expires_at timestamptz not null,
  used_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists auth_tokens_user_idx on public.auth_tokens (user_id, kind);

create table if not exists public.support_tickets (
  id uuid primary key, name text not null, email text not null, message text not null,
  created_at timestamptz not null default now(), status text not null default 'open'
);

-- The audit log cannot be edited or deleted, by anyone, through SQL.
create or replace function public.nq_audit_immutable() returns trigger language plpgsql as $$
begin
  raise exception 'audit_events is append-only';
end $$;
drop trigger if exists audit_no_update on public.audit_events;
create trigger audit_no_update before update or delete on public.audit_events
  for each row execute function public.nq_audit_immutable();

-- Atomic append: take a lock, read the chain head, hash, insert.
-- hash = sha256(prev_hash || canonical_json(event)); the backend sends the canonical JSON.
create or replace function public.nq_audit_append(p_event jsonb, p_canonical text) returns jsonb
language plpgsql set search_path = public as $$
declare
  v_prev text;
  v_row public.audit_events;
begin
  lock table public.audit_events in exclusive mode;
  select hash into v_prev from public.audit_events order by seq desc limit 1;
  v_prev := coalesce(v_prev, repeat('0', 64));
  insert into public.audit_events (id, ts, actor_id, actor_name, action, scan_id, details, prev_hash, hash)
  values ((p_event ->> 'id')::uuid, p_event ->> 'ts', p_event ->> 'actor_id', p_event ->> 'actor_name', p_event ->> 'action',
          p_event ->> 'scan_id', coalesce(p_event -> 'details', '{}'::jsonb), v_prev,
          encode(sha256(convert_to(v_prev || p_canonical, 'UTF8')), 'hex'))
  returning * into v_row;
  return to_jsonb(v_row);
end $$;
revoke all on function public.nq_audit_append(jsonb, text) from public, anon;
grant execute on function public.nq_audit_append(jsonb, text) to authenticated, service_role;
grant all on public.users, public.scans, public.reports, public.audit_events, public.support_tickets, public.auth_tokens to authenticated, service_role;
revoke all on public.users, public.scans, public.reports, public.audit_events, public.support_tickets, public.auth_tokens from anon;

-- ---------- row-level security ----------
create or replace function public.nq_is_service() returns boolean language sql stable as $$
  select coalesce((auth.jwt() -> 'app_metadata' ->> 'nq_role') = 'service', false)
$$;

do $$
declare t text;
begin
  foreach t in array array['users', 'scans', 'reports', 'audit_events', 'support_tickets', 'auth_tokens'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists nq_service_all on public.%I', t);
    execute format('create policy nq_service_all on public.%I for all to authenticated using (public.nq_is_service()) with check (public.nq_is_service())', t);
  end loop;
end $$;

-- ---------- storage: private bucket for scans, heatmaps and signed PDFs ----------
insert into storage.buckets (id, name, public) values ('scans', 'scans', false) on conflict (id) do nothing;
drop policy if exists nq_service_objects on storage.objects;
create policy nq_service_objects on storage.objects for all to authenticated
  using (bucket_id = 'scans' and public.nq_is_service()) with check (bucket_id = 'scans' and public.nq_is_service());
