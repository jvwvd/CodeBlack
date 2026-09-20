from functools import lru_cache

from supabase import Client, create_client

from config import settings


@lru_cache
def get_supabase_client() -> Client:
    """Lazily construct the shared Supabase client (Postgres + Storage)."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        raise RuntimeError(
            "Supabase is not configured: SUPABASE_URL and SUPABASE_KEY "
            "must be set before database or storage access can be used."
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
