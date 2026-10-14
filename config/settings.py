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

# --- 관리 화면의 사용량 탭이 쓰는 값 ---
#
# .env 로 빼지 않는다. 바뀔 일이 드물고 공개돼도 문제없는 값이라, 코드에 두고
# 어디서 온 값인지 옆에 적어 두는 쪽이 낫다. .env 로 두면 배포 설정에도
# 따로 넣어야 하고 그러다 한쪽만 바뀐다.

# 대표님이 미리 넣어 둔 금액 (달러). 「얼마나 썼나」를 이 값에 견준다.
# 10/5 전에 결제하셨으므로 아래 1,011원도 이 금액에서 나갔다.
GEMINI_PREPAID_USD = 5.0

# api_usage 에 쌓이기 전에 쓴 금액 (원).
#
# **구글 결제 화면에서 확인한 값이다** — 어림이 아니라 구글이 매긴 금액이다
# (대표님 캡처, 2026-10-08 확인. 10/2~10/8 총비용 ₩1.01K 이고 10/5~10/6 에
# 몰려 있다. 10/7·10/8 은 0 이라 아래 기록과 겹치지 않는다).
#
# DB 에 줄로 넣지 않는다. 넣으면 종류별·날짜별 집계와 평균이 이 한 줄에 쏠린다 —
# 1건에 1,011원인 평균이 생긴다. 총액에만 더하고 화면은 둘을 나눠 보인다.
GEMINI_SPENT_BEFORE_KRW = 1011

# 위 금액을 쓴 달. 구글 결제 화면의 10/2~10/8 이 모두 10월이다.
#
# 「이번 달 얼마」를 낼 때 이 달이면 위 금액을 함께 더한다. 안 더하면 10월에만
# 210원 쓴 것으로 보인다 — 실제로는 1,221원이다. 11월부터는 쓴 것이 전부
# api_usage 에 남으므로 이 값과 달라져 자동으로 빠진다.
GEMINI_SPENT_BEFORE_MONTH = "2026-10"

# 사용량이 api_usage 에 쌓이기 시작한 날 (첫 줄이 10-07 06:19).
# 화면이 「종류별 비중은 이 날짜부터의 기록 기준」이라고 밝히는 데 쓴다.
# 그 전 사용분은 금액만 알고 종류를 모른다.
USAGE_LOG_FROM = "2026-10-07"

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

# 폼 2 — 「협의 사항 입력폼 (메뉴 확정)」. B/C 갈래에서 메뉴를 확정한 뒤에 보낸다.
#
# **폼 1 과 주소도 문항 번호도 다르다.** 문항 번호는 폼마다 따로 매겨지므로
# 폼 1 의 값을 쓰면 엉뚱한 칸에 코드가 들어간다.
PARTNER_FORM2_URL = os.getenv("PARTNER_FORM2_URL", "")
PARTNER_FORM2_CODE_ENTRY = os.getenv("PARTNER_FORM2_CODE_ENTRY", "")

# --- 수집 대상 지점 ---
# TODO(A): 「서울시 주요 120장소 목록」에서 확인 후 실제 코드값으로 교체
SPOTS = {
    "뚝섬한강공원": "POI093",
    "뚝섬역": "POI025",
}

RAW_DIR = ROOT / "data" / "raw"
PROMPT_DIR = ROOT / "prompts"
