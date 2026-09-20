-- ============================================================
-- backend/schema.sql
--
-- Reproducible definition of the CURRENTLY DEPLOYED Supabase
-- PostgreSQL schema for the Shipping Document Verification project,
-- as documented in PROJECT_RULES.md §14 ("Supabase Persistence
-- Contract"). This file describes what already exists in the live
-- database — it is not a new migration proposal.
--
-- Safe to re-run: every statement is idempotent (CREATE ... IF NOT
-- EXISTS / CREATE OR REPLACE / DROP TRIGGER IF EXISTS before CREATE
-- TRIGGER). It contains no destructive statements — no DROP TABLE,
-- no ALTER TABLE, no DELETE, no TRUNCATE — so re-running it against
-- the live database cannot remove or reset any existing data.
--
-- No RLS policies and no Storage bucket/policy definitions are
-- included here (see the "Storage" note at the end of this file).
-- ============================================================


-- ------------------------------------------------------------
-- Extensions
-- ------------------------------------------------------------
-- None required. gen_random_uuid() (used below) has been a
-- PostgreSQL-core builtin since PG13, and Supabase runs well above
-- that version, so no CREATE EXTENSION statement is needed.


-- ------------------------------------------------------------
-- public.emails
-- ------------------------------------------------------------
create table if not exists public.emails (
    email_id            text primary key,

    category            text
                         check (category in ('BL_COMPARISON','SI_REQUEST','INVOICE_QUERY','GENERAL','SPAM')),
    status              text not null default 'OK'
                         check (status in ('OK','MISMATCH','NEEDS_REVIEW')),
    si                  jsonb,
    bl                  jsonb,
    defect_fields       text[] not null default '{}',
    has_defect          boolean not null default false,

    review_reason       text
                         check (review_reason in ('wrong_doc_type','missing_attachment','unreadable','missing_value')),
    decided_by          text
                         check (decided_by in ('rule','llm')),
    notes               text,

    processing_status   text not null default 'pending'
                         check (processing_status in ('pending','processing','completed','failed')),
    retry_count         integer not null default 0
                         check (retry_count >= 0),
    last_error          text,

    reviewed_at         timestamptz,
    reviewer_notes      text,

    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),

    -- Raw/source organizer fields (see PROJECT_RULES.md §14, "Cloud Import").
    -- Nullable, no defaults — written only by backend/import_organizer_data.py,
    -- never by database.py's upsert_email().
    sender              text,
    subject             text,
    body                text,
    source_attachments  text[]
);


-- ------------------------------------------------------------
-- public.attachments
-- ------------------------------------------------------------
create table if not exists public.attachments (
    id                  uuid primary key default gen_random_uuid(),
    email_id            text not null references public.emails (email_id) on delete cascade,

    doc_type            text
                         check (doc_type in ('SI','BL','OTHER','UNREADABLE')),
    storage_bucket      text not null default 'documents',
    storage_path        text not null,
    original_filename   text not null,
    content_type        text,
    size_bytes          bigint
                         check (size_bytes is null or size_bytes >= 0),
    created_at          timestamptz not null default now(),

    constraint uq_attachments_email_storage_path unique (email_id, storage_path)
);


-- ------------------------------------------------------------
-- Indexes
-- ------------------------------------------------------------
create index if not exists idx_emails_status              on public.emails (status);
create index if not exists idx_emails_category             on public.emails (category);
create index if not exists idx_emails_created_at           on public.emails (created_at);
create index if not exists idx_emails_status_created_at    on public.emails (status, created_at);
create index if not exists idx_emails_processing_status    on public.emails (processing_status);

create index if not exists idx_attachments_email_id on public.attachments (email_id);


-- ------------------------------------------------------------
-- updated_at trigger support
-- ------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_emails_set_updated_at on public.emails;
create trigger trg_emails_set_updated_at
    before update on public.emails
    for each row
    execute function public.set_updated_at();


-- ------------------------------------------------------------
-- Permissions
-- ------------------------------------------------------------
grant select, insert, update, delete
    on table public.emails, public.attachments
    to service_role;


-- ------------------------------------------------------------
-- Storage
-- ------------------------------------------------------------
-- The private Supabase Storage bucket "documents" is configured
-- separately in Supabase Storage (bucket creation + privacy setting
-- are not SQL objects). This file defines PostgreSQL schema objects
-- only — no storage buckets or storage policies are created here.
