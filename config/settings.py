"""환경변수 로딩. 로컬은 .env, GitHub Actions는 Secrets."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _req(key: str) -> str:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"환경변수 {key} 가 없습니다. .env 또는 GitHub Secrets를 확인하세요.")
    return v


# --- API 키 ---
SEOUL_API_KEY     = os.getenv("SEOUL_API_KEY", "")
DATA_GO_KR_KEY    = os.getenv("DATA_GO_KR_KEY", "")
SEOUL_CULTURE_KEY = os.getenv("SEOUL_CULTURE_KEY", "")
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL      = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# --- Supabase ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# --- 바틀링 ---
BOTTLING_LAT = float(os.getenv("BOTTLING_LAT", "37.5305"))
BOTTLING_LNG = float(os.getenv("BOTTLING_LNG", "127.0664"))

# --- 수집 대상 지점 ---
# TODO(A): 「서울시 주요 120장소 목록」에서 확인 후 실제 코드값으로 교체
SPOTS = {
    "뚝섬한강공원": "POI093",
    "뚝섬역": "POI025",
}

RAW_DIR = ROOT / "data" / "raw"
PROMPT_DIR = ROOT / "prompts"
