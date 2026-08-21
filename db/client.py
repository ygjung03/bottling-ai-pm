"""Supabase 연결 공통 모듈. A/B 모두 이걸 사용한다."""
from functools import lru_cache
from supabase import create_client, Client
from config.settings import SUPABASE_URL, SUPABASE_KEY


@lru_cache(maxsize=1)
def get_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY 가 설정되지 않았습니다.")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def upsert(table: str, rows: list[dict], on_conflict: str | None = None):
    """중복 시 갱신. rows가 비면 아무것도 하지 않는다."""
    if not rows:
        return None
    q = get_client().table(table)
    return (q.upsert(rows, on_conflict=on_conflict) if on_conflict else q.upsert(rows)).execute()


def select(table: str, columns: str = "*", **filters):
    q = get_client().table(table).select(columns)
    for k, v in filters.items():
        q = q.eq(k, v)
    return q.execute().data
