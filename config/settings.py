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
GEMINI_MODEL      = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# 유료 키. 없으면 무료 키를 쓴다.
#
# 기획안 생성이 이 키를 쓴다. 보낸 내용이 모델 개선에 쓰이지 않게 하려는
# 것이다 — 기획안에는 협력사가 알려준 매입가가 들어간다.
#
# 메뉴 수집은 블로그에 공개된 메뉴와 가격만 넘기므로 지금은 무료 키다. 다만
# 분당 한도에 여러 번 걸리면 유료로 넘기는 것을 검토 중이어서, 사용량 기록은
# 「어느 기능인가」가 아니라 호출이 실제로 쓴 키를 기준으로 삼는다.
GEMINI_API_KEY_PAID = os.getenv("GEMINI_API_KEY_PAID", "") or GEMINI_API_KEY

# --- 제미나이 단가 (사용량 기록용) ---
#
# 100만 토큰당 미국 달러. 공식 단가표에서 옮겼다 (2026-10-06 확인).
#   https://ai.google.dev/gemini-api/docs/pricing
#
# 단가나 환율이 바뀌면 .env 로 덮는다. 이미 남은 기록은 그때 쓴 환율을 함께
# 들고 있어서 여기 값을 바꿔도 소급되지 않는다 (db/api_usage.py).
GEMINI_USD_PER_M_INPUT  = float(os.getenv("GEMINI_USD_PER_M_INPUT", "0.30"))
GEMINI_USD_PER_M_OUTPUT = float(os.getenv("GEMINI_USD_PER_M_OUTPUT", "2.50"))
KRW_PER_USD             = float(os.getenv("KRW_PER_USD", "1350"))

# 네이버 검색 API — NCP(API HUB) 키다. 개발자센터 키가 아니라서 주소도 헤더
# 이름도 다르다 (collectors/menu_reviews.py 참고). 10/5 에 셋 다 호출해 확인했다.
NAVER_CLIENT_ID     = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")

# --- Supabase ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# --- 바틀링 ---
BOTTLING_LAT = float(os.getenv("BOTTLING_LAT", "37.5318919"))
BOTTLING_LNG = float(os.getenv("BOTTLING_LNG", "127.0679483"))

# --- 협력사 폼 ---
#
# 「협의 사항 입력폼」의 주소와, 「확인 코드는 무엇인가요?」 문항의 번호.
# 둘을 합쳐 협력사마다 코드가 박힌 링크를 만든다.
#
#   {URL}?usp=pp_url&{ENTRY}={초대 코드}
#         어느 문항에 ↑        무엇을 넣을지 ↑
#
# ENTRY 는 값이 아니라 **문항을 가리키는 이름표**다 (entry.1920643830 같은
# 모양). 협력사가 바뀌어도 이 이름표는 그대로이고, 뒤에 붙는 초대 코드만 바뀐다.
#
# 미리 채우는 이유는 손으로 적다 틀리는 것을 막기 위해서다. 코드가 어긋나면
# 폼은 통과시키고(형식만 본다) .gs 가 맞는 협력사를 못 찾아 아무것도 저장하지
# 않는다 — 제출은 됐는데 DB 에 없는 상태가 된다.
#
# 공개 저장소라 값을 코드에 적지 않는다. .env 와 Cloud secrets 에만 둔다.
PARTNER_FORM_URL = os.getenv("PARTNER_FORM_URL", "")
PARTNER_FORM_CODE_ENTRY = os.getenv("PARTNER_FORM_CODE_ENTRY", "")

# --- 수집 대상 지점 ---
# TODO(A): 「서울시 주요 120장소 목록」에서 확인 후 실제 코드값으로 교체
SPOTS = {
    "뚝섬한강공원": "POI093",
    "뚝섬역": "POI025",
}

RAW_DIR = ROOT / "data" / "raw"
PROMPT_DIR = ROOT / "prompts"
