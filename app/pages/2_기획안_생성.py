"""
기획안 생성 — 핵심 화면 (T22, 명세서 4-2)

체인 4단계를 순차 실행한다. 실측 약 20초라 동기 방식으로 충분하다.
다만 무반응 구간이 길게 느껴지고 어느 단계에서 멈췄는지 보여야 하므로
단계별 진행 표시는 유지한다 (명세서 6-2-3).

[결과를 세션에 남긴다]
  Streamlit 은 위젯을 건드릴 때마다 스크립트를 처음부터 다시 돌린다.
  결과를 지역 변수에 두면 탭을 옮기거나 expander 를 여는 순간 사라지고,
  20초짜리 체인이 다시 돈다. session_state 에 넣어야 한다.

[미구현 기능은 화면에 흔적을 남기지 않는다]
  메뉴 이미지(T43)·채택 폐기(T23)는 아직 없다.
  자리표시자를 두지 않고 그 영역째 감춘다. 대표님이 보는 화면에
  개발 티켓 번호가 나오면 안 된다.

[기획안은 두 회차로 나간다]
  1차  협력사가 아무것도 입력하기 전. 파트너 추천에서 등록만 된 상태라
       partners 행에 이름·업종뿐이고, 메뉴·판매가는 블로그 후기 수집이
       채운다(네이버 검색 API). 그 값으로 기획안을 만들어 제안서를 먼저
       보낸다. 납품가·납품 요일·제약은 비어 있는 것이 정상이다 — 체인이
       「데이터 없음」으로 받는다.
  2차  협력사가 하겠다고 해서 구글 폼을 낸 뒤. 폼 값이 partners 에
       들어와 있으므로 그대로 다시 만든다.
  어느 회차인지는 폼 값이 있는지로 가른다. plans.round 에 남긴다.
  메뉴·판매가가 아직 없으면 만들지 않는다 — 완제품을 사 와 파는 협업이라
  무엇을 파는지 모르면 기획안이 성립하지 않는다. 화면에서 손으로 받는
  칸은 두지 않는다.
"""
import json
import re
import subprocess
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

import _path  # noqa: F401  (프로젝트 루트를 sys.path 에 추가)
import streamlit as st

from app.auth import require_owner
from app.proposal import (build_proposal_docx, build_proposal_pdf, end_dot,
                          missing_fields, pdf_pages, proposal_no)
from app.theme import (ARCHIVE_PARAM, SS_ARCHIVE_COUNT, SS_PARTNER_ID,
                       apply_chrome)
from app.ui import page_header
from chain.inputs import (BOTTLING_INGREDIENTS, BOTTLING_SNS, MARGIN_REF,
                          NO_TREND_MENU, PAST_CASES, WEATHER_PREF,
                          build_beer_list, build_constraints, build_events,
                          build_partner_blockers, build_partner_resources,
                          build_partner_sns, build_rec_reason, menu_rows)
from chain.runner import run
from config.settings import PARTNER_FORM_CODE_ENTRY, PARTNER_FORM_URL
from context.builder import build as build_context
from db.client import get_client

st.set_page_config(page_title="기획안 생성", page_icon="📝", layout="wide",
                   initial_sidebar_state="collapsed")
require_owner()
# apply_chrome 은 화면 앞부분에서 부른다. 상단 바의 보관함 개수를 그리기 전에
# 세어야 하는데, 그러려면 아래 조회 함수들이 먼저 정의돼 있어야 한다.

KST = timezone(timedelta(hours=9))
SS_RESULT = "plan_result"      # 체인 출력
SS_META = "plan_meta"          # 협력사·날짜 등 생성 조건

# SS_PARTNER_ID(고른 협력사 id)는 app/theme.py 에 있다 — 파트너 추천도 쓴다.

# 보관함. 열렸는지는 주소의 질의 문자열이 정한다 (app/theme.ARCHIVE_PARAM).
#
# 「최종 선택」으로 정한 보낸 안은 세션이 아니라 DB 에 있다 (plans.sent_option,
# db/migrate_0930.sql). 1차 제안서를 보내고 며칠 뒤에 폼이 오므로 그 사이
# 브라우저가 반드시 끊긴다.
SS_ARCHIVE_WARN = "archive_warn"   # 둘 이상 골라 되돌렸다 — 창을 띄울 표시
SS_ARCHIVE_SWAP = "archive_swap"   # 보낸 안을 바꾸려 한다 — 확인 창에 넘길 값
SS_ARCHIVE_NOTE = "archive_note"   # 보관함에서 띄울 알림 한 줄

# 접근마다 색을 둔다. 탭이 셋인데 내용이 비슷해 어느 안을 보고 있는지
# 놓치기 쉽다 (9/19 화면 확인). 탭 배지와 카드 배지에 같은 색을 쓴다.
# (테두리, 글자, 바탕). 파스텔 테두리에 같은 계열의 진한 글자,
# 바탕은 더 연한 불투명 파스텔 — 탭이 겹치는 자리가 비치지 않게 (9/20).
TAB_COLOR = {
    "단품": ("#9DC3E6", "#2F5D8A", "#E3EEF8"),
    "세트": ("#F7C59F", "#8A5A1E", "#FCEEE0"),
    "포장": ("#B5D99C", "#4A6B2A", "#EAF3E2"),
}

# 나란히 둔 상자의 높이를 서로 맞춘다.
#
# 높이를 숫자로 고정하지는 않는다. 내용이 넘치면 잘린 채로 보이는데
# 스크롤이 되는지조차 알 수 없어, 더 있다는 사실을 모른다.
#
# 그래서 긴 쪽에 맞춰 늘린다. 컬럼(stColumn)은 이미 서로 같은 높이로
# 늘어나 있으나 그 안의 테두리 상자가 제 내용만큼만 차지해서, 짧은 쪽이
# 위로 붙어 보인다. 상자를 컬럼 높이만큼 채우면 둘이 같아진다.
EQUAL_HEIGHT_BOXES = """
<style>
  [data-testid="stColumn"] [data-testid="stVerticalBlockBorderWrapper"] {
    height: 100%;
  }
</style>
"""


# ══════════════════════════════════════════
# 조회
# ══════════════════════════════════════════

@st.cache_data(ttl=60)
def load_partners() -> list[dict]:
    """협력사 목록. T21 폼이 붙으면 여기에 실제 입력이 쌓인다."""
    try:
        # 행을 통째로 가져온다.
        #
        # 고를 때 쓰는 것은 이름과 협의 가능 시간뿐이지만, 고른 뒤 그대로
        # 체인에 넘어간다. 필요한 칸을 골라 적었더니 메뉴·대표메뉴·납품
        # 요일이 빠져 기획안이 전부 "데이터 없음"으로 나왔다 (#17).
        # partners 는 행이 작아 통째로 가져와도 된다.
        return (get_client().table("partners").select("*")
                .order("id").execute().data or [])
    except Exception as e:
        st.error(f"협력사 조회 실패: {e}")
        return []


def has_form(partner: dict) -> bool:
    """
    구글 폼이 들어왔는가. 폼이 채우는 값이 하나라도 있으면 들어온 것이다.

    폼에서 납품 요일과 제약은 필수라 제출했으면 반드시 있다. 메뉴·가격은
    1차에서 후기로 먼저 채우므로 근거가 되지 못한다.
    """
    return any(partner.get(k) for k in
               ("available_slots", "blockers", "sns_channel"))


def round_of(partner: dict) -> int:
    """기본 회차. 폼이 있으면 2차를 먼저 보인다 — 고르는 것은 사람이다."""
    return 2 if has_form(partner) else 1


def menu_block(partner: dict) -> str | None:
    """
    2차를 막아야 하면 그 이유, 괜찮으면 None.

    갈래마다 확정 메뉴가 어디서 오는 곳이 다르다 (partners.reply_choice).

      A    제안받은 그 메뉴다. 폼이 묻지 않아 보관함에서 고른 안을 쓴다
      A2   협의로 정한 다른 메뉴. 폼 1 이 이름을 받는다
      B·C  메뉴를 다시 고르겠다는 뜻. 이름은 폼 2 에서 온다

    B·C 는 협력사가 그 메뉴를 **거절한** 것이라, 새 메뉴가 오기 전에 2차를
    만들면 거절한 메뉴로 확정 기획안이 나간다. 경고도 안 뜬다 — 코드가 폼
    값이 없으면 화면이 든 값을 쓰기 때문이다 (chain/inputs.py). 그래서 막는다.

    갈래를 모르면(값이 비면) 막지 않는다. 폼이 오기 전이거나 옛 응답인데,
    가장 흔한 A 를 막아 버리면 정상 흐름이 멈춘다.
    """
    if partner.get("agreed_menu"):
        return None
    branch = (partner.get("reply_choice") or "").strip().upper()
    if branch in ("B", "C"):
        return ("협력사가 메뉴를 다시 추천받고 싶다고 했습니다. "
                "메뉴를 정한 뒤 두 번째 구글폼을 받아야 2차를 만들 수 있습니다.")
    if branch == "A2":
        return ("협의로 정한 메뉴가 폼에 들어오지 않았습니다. "
                "폼을 다시 제출해야 합니다.")
    return None


def prompt_version() -> str | None:
    """
    prompts/ 디렉터리의 git 해시.

    프롬프트를 고친 뒤 결과가 나빠졌을 때 어느 버전으로 만든 기획안인지
    알아야 비교가 성립한다 (명세서 5-5). 실패해도 생성은 막지 않는다.
    """
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD:prompts"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip() or None
    except Exception:
        return None


def save_plan(result: dict, meta: dict) -> int | None:
    """
    생성 결과를 plans 에 남긴다.

    체인이 중간에 끊기면 final_output 이 없다. 그 컬럼이 NOT NULL 이라
    저장할 수 없으므로 건너뛴다. 화면에는 살아남은 단계를 그대로 보여준다.
    """
    if not result.get("final"):
        return None
    try:
        rows = get_client().table("plans").insert({
            "partner_id": meta["partner_id"],
            "partner_source": "manual",     # 추천 엔진 미구현 — 직접 지정
            "round": meta["round"],
            # 2차가 어느 1차를 이어받았는지 (보관함에서 고른 안이 든 plan).
            "prev_plan_id": meta.get("prev_plan_id"),
            "date_mode": "fixed",
            "target_date": meta["target_date"],
            "context_snapshot": meta["context"],
            "p1_output": result["p1"],
            "p2_output": result["p2"],
            "p3_output": result["p3"],
            "final_output": result["final"],
            # 되감기 기록도 남긴다. 몇 건이 재호출까지 갔고 그중 몇 건이
            # 통과로 바뀌었는지를 나중에 세려면 이 값이 있어야 한다
            # (docs/검증루프_도입안.md 8장).
            "auto_check": {"issues": result["issues"],
                           "rewinds": result["rewinds"],
                           "restarts": result["restarts"]},
            "latency_ms": result["latency_ms"],
            "prompt_version": meta["prompt_version"],
        }).execute().data or []
        return rows[0]["id"] if rows else None
    except Exception as e:
        st.warning(f"기획안은 만들어졌으나 저장에 실패했습니다 — {e}")
        return None


def save_adopted(plan_id: int | None, options: list[str]) -> bool:
    """
    고른 안을 plans 에 남긴다. 여러 개 고를 수 있다 — 협력사에게 "둘 중 편한 걸로"
    라고 주는 편이 하나만 들이미는 것보다 낫다 (9/25).

    다시 생성해도 지난 기록은 지우지 않는다. 1차를 다시 만들면 새 plans 행이
    생기고 옛 행의 채택은 그대로 남는다 — 그 쌓인 것이 보관함의 내용물이다.

    **빈 목록은 NULL 로 넣는다.** 빈 문자열이나 `[]` 를 넣으면 「아무것도 안
    골랐다」가 「골랐다」로 읽힌다. 실제로 이 함수가 두 번 정의돼 있어 리스트가
    그대로 저장되면서 `'[]'` 가 들어간 적이 있다 (9/30에 고침).
    """
    if not plan_id:
        st.warning("저장되지 않은 기획안이라 선택을 남길 수 없습니다.")
        return False
    try:
        (get_client().table("plans")
         .update({"adopted_option": ",".join(options) if options else None,
                  "status": "adopted" if options else "generated"})
         .eq("id", plan_id).execute())
        # 이 값을 읽는 조회가 둘이다. 하나만 비우면 다른 쪽이 30초 동안 옛
        # 결과를 내놓아, 담았는데 보관함이 비어 보인다 (9/30).
        load_adopted.clear()
        load_archive.clear()
        return True
    except Exception as e:
        st.warning(f"선택을 저장하지 못했습니다 — {e}")
        return False


@st.cache_data(ttl=30)
def load_adopted(partner_id: int) -> list[dict]:
    """
    이 협력사의 1차 중 안을 고른 것들. 최신순.

    가장 최근 1차만 보지 않는다 — 여러 번 생성하며 마음에 드는 것을 모아 둘 수
    있고, 그 목록이 곧 보관함이다 (9/25).

    조회는 NULL 만 걸러낸다. 값이 비어 있는 행도 담은 것이 없는 것이므로
    여기서 걸러낸다. 이 값 하나로 2차 버튼이 열리고 닫힌다.
    """
    try:
        rows = (get_client().table("plans")
                .select("id,adopted_option,sent_option,target_date,"
                        "created_at,final_output")
                .eq("partner_id", partner_id).eq("round", 1)
                .not_.is_("adopted_option", "null")
                .order("id", desc=True).limit(20).execute().data or [])
    except Exception:
        return []
    return [r for r in rows if adopted_ids(r.get("adopted_option"))]


@st.cache_data(ttl=30)
def load_archive(partner_id: int) -> list[dict]:
    """
    보관함에 보일 것 — 바틀링측에서 해당 협력사와 협력하기 위해 생성한 안중 마음에 들어 담아 둔 안. 1차와 2차를 모두 가져온다.

    2차도 여러 번 돌려 마음에 드는 것을 담아 둘 수 있고, 실제로 실행하는 것은
    그중 하나다. 그래서 보관함은 회차를 가리지 않는다.

    회차끼리 묶어 보여주려고 round 로 먼저 정렬한다. id 순으로만 두면 1차와
    2차를 번갈아 만들었을 때 목록이 섞인다.

    load_adopted() 와 조회가 거의 같은데도 따로 둔 이유는 쓰는 곳이 달라서다.

      load_adopted   2차 버튼을 열지 정한다. 1차에 담은 것이 있어야 열리므로
                     1차만 본다
      load_archive   보관함에 무엇을 보여줄지 정한다. 담은 것이면 회차를
                     가리지 않는다

    한 함수로 합치면 부르는 곳마다 어느 뜻인지 매번 따져야 한다.
    """
    try:
        rows = (get_client().table("plans")
                .select("id,round,adopted_option,sent_option,target_date,"
                        "created_at,final_output")
                .eq("partner_id", partner_id)
                .not_.is_("adopted_option", "null")
                .order("round").order("id", desc=True)
                .limit(40).execute().data or [])
    except Exception:
        return []
    return [r for r in rows if adopted_ids(r.get("adopted_option"))]


def sent_options(picks: list[dict]) -> list[dict]:
    """
    담아 둔 안을 하나씩 펼친다. 보관함에 한 줄씩 보이는 것이 이것이다.

    담는 것은 여럿이고 보내는 것은 하나다 (쟁점 1-1-2). 제안서를 보내는 일은
    화면 밖(메일·카톡)에서 일어나므로 담는 시점에는 아직 안 정해졌을 수 있지만,
    2차를 만들 때는 반드시 정해져 있어야한다.

    plans 한 행에 안이 여럿 담겼을 수 있고(`"A,C"`) 여러 번 생성하며 행이
    쌓이므로, 둘을 펼쳐 한 줄씩 만든다.
    """
    out = []
    for p in picks:
        items = {i.get("안_id"): i
                 for i in ((p.get("final_output") or {}).get("안") or [])}
        for aid in adopted_ids(p.get("adopted_option")):
            it = items.get(aid) or {}
            out.append({
                "key": f"{p['id']}-{aid}",
                "plan_id": p["id"],
                "round": p.get("round") or 1,
                "안_id": aid,
                "메뉴명": it.get("메뉴명") or f"{aid}안",
                "접근": it.get("접근") or "",
                "선정_사유": it.get("선정_사유") or "",
                "판매가_제안": it.get("판매가_제안"),
                "target_date": p.get("target_date"),
                "created_at": p.get("created_at"),
                "보냄": p.get("sent_option") == aid,
                "item": it,        # 미리보기가 쓴다 — 안 내용 통째
            })
    return out


def sent_pick(options: list[dict]) -> dict | None:
    """이 협력사의 「보낸 안」. 없으면 None."""
    return next((o for o in options if o["보냄"]), None)


def save_sent(partner_id: int, plan_id: int, option_id: str) -> bool:
    """
    「협력사에 보낸 안」을 DB 에 남긴다.

    한 협력사에 보낸 안은 하나다. 다른 행에 남아 있던 표시를 먼저 비우고
    새 행에 적는다 — UNIQUE 를 안 걸었으므로(db/migrate_0930.sql) 순서를
    여기서 지킨다.

    세션이 아니라 DB 에 두는 이유는, 1차 제안서를 보내고 며칠 뒤에 폼이 와서
    그 사이 브라우저가 반드시 끊기기 때문이다.
    """
    try:
        cli = get_client()
        (cli.table("plans").update({"sent_option": None, "sent_at": None})
         .eq("partner_id", partner_id)
         .not_.is_("sent_option", "null").execute())
        (cli.table("plans")
         .update({"sent_option": option_id,
                  "sent_at": datetime.now(KST).isoformat()})
         .eq("id", plan_id).execute())
        load_adopted.clear()
        load_archive.clear()
        return True
    except Exception as e:
        st.warning(f"보낸 안을 저장하지 못했습니다 — {e}")
        return False


def adopted_ids(value) -> list[str]:
    """`plans.adopted_option` 에 담긴 안_id 목록. 형식은 `"A,C"` 다."""
    if not value:
        return []
    return [p.strip() for p in str(value).split(",") if p.strip()]


# ══════════════════════════════════════════
# 생성
# ══════════════════════════════════════════

def has_agreed_plan(partner: dict) -> bool:
    """
    협력사가 동의한 안이 이미 있나. 있으면 그 안을 그대로 쓴다.

      A      보낸 안에 「그 메뉴로 하겠다」고 답했다   있다
      A2     보낸 안 대신 다른 메뉴로 바꿨다          없다 — 새로 만든다
      B/C    보낸 안을 거절했다                     없다 — 새로 만든다

    B/C 는 메뉴판을 읽어 다시 고른 안이 있어야 하는데 그 화면이 아직 없다.
    (남은_작업 ③-c). 생기면 여기에 B·C 를 더하면 된다 — 그 화면이 고른 안을
    보관함과 같은 방식으로 남기므로 뒷일은 같다.
    """
    return (partner.get("reply_choice") or "A").strip().upper() == "A"


def load_preset(partner: dict, sent: dict | None) -> dict | None:
    """
    2차에서 다시 만들지 않고 가져다 쓸 1차 결과.

    협력사가 「그 메뉴로 하겠다」고 했으면 1차에서 고른 그 안이 곧 확정안이다.
    다시 만들면 값이 달라진다 — 10/2 에 세트 판매가가 9,000원에서 7,500원으로
    바뀌었다. 협력사가 동의한 것과 다른 문서가 나간다.

    그래서 그 안을 그대로 가져오고, 협의로 정해진 것만 덮는다. 나머지(바틀링
    예정 판매가·구성·페어링 맥주)는 1차 그대로 둔다.

    메뉴를 새로 정한 경우(A2)는 쓸 안이 없어 None 을 돌려준다.
    """
    if not sent or not has_agreed_plan(partner):
        return None
    try:
        row = (get_client().table("plans").select("p1_output,p2_output")
               .eq("id", sent["plan_id"]).single().execute().data)
    except Exception:
        return None
    menus = (row.get("p2_output") or {}).get("메뉴안") or []
    item = next((m for m in menus if m.get("안_id") == sent["안_id"]), None)
    if not row.get("p1_output") or not item:
        return None

    item = dict(item)
    # 협력사 정가는 1차에서 후기를 바탕으로 추정한 값이다. 폼으로 실제 값을 받았으면 그것이
    # 맞는 값이다. 안 바꾸면 (4)가 틀린 정가를 근거로 판매가를 설명한다.
    #
    # 세트의 「정가_합」은 협력사 정가 + 맥주 500ml 값이다. 정가가 움직인
    # 만큼 같이 움직여야 제안서의 「따로 사면 N원」이 맞는다.
    sale, was = partner.get("agreed_sale_price"), item.get("협력사_정가")
    if sale:
        item["협력사_정가"] = int(sale)
        if was and item.get("정가_합"):
            item["정가_합"] = int(item["정가_합"]) + int(sale) - int(was)
    if partner.get("agreed_price"):
        item["협력사희망_매입가"] = f"{int(partner['agreed_price']):,}원 [확정]"
    if partner.get("supply_qty"):
        item["1회_납품_수량"] = partner["supply_qty"]
    if partner.get("storage_note"):
        item["보관_조건"] = partner["storage_note"]

    return {"p1": row["p1_output"],
            "p2": {"메뉴안": [item],
                   "공통_주의사항": (row.get("p2_output") or {}).get("공통_주의사항") or []}}


def screen_approach(partner: dict, sent: dict | None) -> str | None:
    """
    화면이 아는 판매 방식. 폼이 묻는 갈래면 넘기지 않는다.

    판매 방식이 어디서 오는지는 갈래마다 하나뿐이어야 한다. 둘 다 오면 어느
    것이 맞는지 따질 일이 생긴다.

      A      화면에서 고른 안에 들어 있다        → 화면을 넘긴다
      A2     폼 섹션 2 에서 받는다       → 화면을 넘기지 않는다. 메뉴가 바뀌었으니
                                        화면에서 골랐던건 더이상 의미가 없다.
      B/C    화면에서 고른 안에 들어 있다  → 화면을 넘긴다 (그 화면은 아직 없다)
    """
    if (partner.get("reply_choice") or "").strip().upper() == "A2":
        return None
    return (sent or {}).get("접근")


def generate(partner: dict, target: date, rnd: int,
             sent: dict | None = None) -> None:
    """
    체인을 돌리고 결과를 세션에 남긴다.

    rnd 는 사람이 고른 회차다. 전에는 폼 값이 있으면 무조건 2차로 떠서 1차 과정을
    보여줄 수 없었다 (9/24).

    2차면 협의 결과를 AI 에게 넘긴다 (9/29). 안 넘기면 협력사가 폼에 적은 매입가를
    AI 가 못 봐서 2차가 1차와 같은 값을 낸다.

    sent 는 보관함에서 고른 「협력사에 보낸 안」이다. 그 안의 메뉴가 협업 메뉴다.
    A 갈래(「네, 그 메뉴로 진행하겠습니다」)는 폼이 메뉴 이름을 묻지 않아 이 값
    말고는 알 길이 없다. 안 넘기면 AI 가 협의 전 목록에서 다른 메뉴를 고른다.
    """
    with st.status(f"{rnd}차 기획안 생성 중...", expanded=True) as box:
        step_slot = st.empty()

        def on_step(n: int, label: str) -> None:
            step_slot.write(f"({n}/4) {label}")

        try:
            ctx = build_context(target, partner_category=partner.get("category"))
        except Exception as e:
            box.update(label="상권 데이터를 읽지 못했습니다", state="error")
            st.error(f"컨텍스트 빌더 실패: {e}")
            return

        result = run(
            context=ctx,
            target_date=target.isoformat(),
            beer_list=build_beer_list(),
            partner_res=build_partner_resources(
                partner, confirmed=rnd == 2,
                agreed_menu=(sent or {}).get("메뉴명"),
                agreed_approach=screen_approach(partner, sent)),
            partner_blockers=build_partner_blockers(partner),
            bottling_ingredients=BOTTLING_INGREDIENTS,
            margin_ref=MARGIN_REF,
            weather_pref=WEATHER_PREF,
            trend_menu=NO_TREND_MENU,
            constraints=build_constraints(),
            fewshot="(없음 — 채택 사례가 아직 없다)",
            bottling_sns=BOTTLING_SNS,
            partner_sns=build_partner_sns(partner),
            events=build_events(target),
            past_cases=PAST_CASES,
            rec_reason=build_rec_reason(partner),
            partner=partner,
            fixed_menu=rnd == 2,
            preset=load_preset(partner, sent) if rnd == 2 else None,
            on_step=on_step,
        )

        sec = result["latency_ms"] / 1000
        if result["error"]:
            box.update(label=f"{rnd}차 기획안을 끝까지 만들지 못했습니다", state="error")
        else:
            box.update(label=f"{rnd}차 기획안 완료 — {sec:.0f}초", state="complete")

    meta = {
        "partner_id": partner["id"],
        "partner_name": partner["name"],
        "round": rnd,
        "target_date": target.isoformat(),
        "context": ctx,
        "prompt_version": prompt_version(),
        # 2차가 어느 1차를 이어받았는지. 보관함에서 고른 그 안이 든 plan 이다.
        "prev_plan_id": (sent or {}).get("plan_id"),
        # 제안서의 「포장 판매」 줄. 협력사가 폼에 답한 값이다.
        "takeout": partner.get("takeout"),
    }
    meta["adopted"] = []            # 새로 만든 기획안이라 아직 담은 안이 없다
    meta["plan_id"] = save_plan(result, meta)
    st.session_state[SS_RESULT] = result
    st.session_state[SS_META] = meta
    # 이전 기획안의 제안서 파일과 미리보기 페이지 위치를 버린다
    st.session_state[SS_FILES] = {}
    for k in [k for k in st.session_state if k.startswith("page_")]:
        del st.session_state[k]


# ══════════════════════════════════════════
# 결과 표시
# ══════════════════════════════════════════

SS_FILES = "proposal_files"   # 안별 제안서 파일 캐시. 생성할 때마다 비운다.
SS_TOAST = "adopt_toast"      # 담긴 개수. rerun 뒤에 토스트로 띄우고 지운다.


def flash_note(msg: str | None, seconds: float = 2.0) -> None:
    """
    화면 가운데에 떴다 잠시 뒤 사라지는 알림. None 이면 아무것도 안 그린다.

    seconds 는 **다 보이는 시간**이다. 그 뒤 0.4초에 걸쳐 흐려진다.
    읽을 글자가 많으면 늘린다 — 보관함 알림이 그래서 3.5초다.

    st.toast 는 오른쪽 아래 구석이라 눈에 안 띄고 위치를 CSS 로 못 옮겼다
    (9/25). 부르는 곳은 화면 맨 끝이어야 한다 — 위에 두면 알림이 사라질 때
    아래 내용이 밀린다.
    """
    if not msg:
        return
    # 애니메이션 이름과 class 에 매번 다른 번호를 붙인다. 같은 이름이 이미 DOM 에
    # 있으면 브라우저가 애니메이션을 다시 시작하지 않아 배너가 안 보인다.
    tag = f"f{int(datetime.now(KST).timestamp() * 1000) % 100000}"
    total = seconds + 0.4
    hold = round(seconds / total * 100)
    st.markdown(
        f'<style>@keyframes {tag} {{ 0%,{hold}% {{opacity:1}} 100% {{opacity:0; visibility:hidden}} }}'
        f'.{tag} {{ position:fixed; left:50%; top:50%; transform:translate(-50%,-50%);'
        f'  z-index:100000; background:#111827; color:#fff; padding:22px 40px;'
        f'  border-radius:14px; font-size:1.3rem; font-weight:700; white-space:nowrap;'
        f'  box-shadow:0 16px 48px rgba(0,0,0,0.35);'
        f'  animation: {tag} {total}s ease forwards; }}</style>'
        f'<div class="{tag}">📄 {msg}</div>', unsafe_allow_html=True)


def _proposal_files(item: dict, meta: dict, cache_key: str | None = None) -> dict:
    """
    안 하나의 제안서 파일 — docx, pdf, 페이지 이미지. 세션에 캐시한다.

    Word 변환이 안마다 5~8초라 화면이 다시 그려질 때마다 하면 안 된다.
    탭을 옮기거나 페이지를 넘길 때마다 스크립트가 다시 도는데, 그때는 여기서
    바로 꺼낸다. 캐시는 generate() 가 새 기획안을 만들 때 비운다.

    cache_key 는 보관함이 쓴다. 안_id 만으로는 여러 기획안의 A안이 한 칸을
    나눠 써서 남의 제안서가 뜬다.
    """
    cache = st.session_state.setdefault(SS_FILES, {})
    key = cache_key or item.get("안_id")
    if key not in cache:
        # PDF 는 reportlab 으로 직접 만든다 — 어디서나 같은 문서 (9/22).
        # 전에는 Word 로 변환해서 Word 없는 클라우드에선 HTML 근사판이었다.
        docx = build_proposal_docx(item, meta)
        pdf = build_proposal_pdf(item, meta)
        cache[key] = {"docx": docx, "pdf": pdf, "pages": pdf_pages(pdf)}
    return cache[key]


def render_proposal(item: dict, meta: dict) -> None:
    """
    안마다 붙는다. 대표가 고른 안이 그대로 제안서가 된다.

    9/19 전엔 (4)가 순위를 매기고 1위에만 제안서 필드를 채웠다. 접근이
    다른 세 안에 순위가 무의미해 순위를 없앴고, 어느 안이 골라질지 모르니
    (4)가 모든 안에 필드를 채운다.
    """
    missing = missing_fields(item)
    if missing:
        st.warning(f"제안서를 만들 수 없습니다 — 이 안에 {', '.join(missing)}이(가) 없습니다. "
                   f"다시 생성해 주세요.")
        return

    aid = item.get("안_id") or "?"
    st.markdown(
        '<div style="display:flex; align-items:center; gap:14px; margin:22px 0 14px; '
        'color:#9CA3AF; font-size:0.72rem; letter-spacing:0.1em">'
        '<span style="flex:1; border-top:1px solid #E5E7EB"></span>DOCUMENT PREVIEW'
        '<span style="flex:1; border-top:1px solid #E5E7EB"></span></div>',
        unsafe_allow_html=True)

    with st.spinner("제안서를 만드는 중..."):
        files = _proposal_files(item, meta)

    # 종이 모양 미리보기 (시안 docs/ref/피그마_예시2.pdf). 회색 바탕 위에 흰 종이,
    # 양옆에 ‹ › 버튼. 내려받는 PDF 의 실제 페이지를 그대로 보인다.
    # 바탕색·버튼 높이는 key 로 붙는 st-key-* 클래스에 CSS 를 준다.
    st.markdown(
        f'<style>'
        f'.st-key-paper_{aid} {{ background:#F1F5F9; border-radius:12px; padding:28px 12px; }}'
        f'.st-key-paper_{aid} [data-testid="stImage"] img {{'
        f'  box-shadow:0 6px 24px rgba(15,23,42,0.14); }}'
        f'.st-key-prev_{aid} button, .st-key-next_{aid} button {{'
        f'  height:72px; width:100%; color:#64748B; background:transparent; border:none; }}'
        f'.st-key-prev_{aid} button p, .st-key-next_{aid} button p {{'
        f'  font-size:2.8rem; line-height:1; font-weight:300; }}'
        f'.st-key-prev_{aid} button:hover, .st-key-next_{aid} button:hover {{'
        f'  background:#E2E8F0; color:#1E293B; }}'
        f'</style>', unsafe_allow_html=True)
    with st.container(key=f"paper_{aid}"):
        pages = files["pages"]
        key = f"page_{aid}"
        idx = st.session_state.get(key, 0)
        idx = max(0, min(idx, len(pages) - 1))
        c_l, c_mid, c_r = st.columns([1, 7, 1], vertical_alignment="center")
        if c_l.button("‹", key=f"prev_{aid}", disabled=idx == 0):
            st.session_state[key] = idx - 1
            st.rerun()
        if c_r.button("›", key=f"next_{aid}", disabled=idx >= len(pages) - 1):
            st.session_state[key] = idx + 1
            st.rerun()
        c_mid.image(pages[idx], use_container_width=True)
        st.markdown(f'<div style="text-align:center; color:#9CA3AF; font-size:0.75rem; '
                    f'margin-top:10px">Page {idx + 1} of {len(pages)}</div>',
                    unsafe_allow_html=True)

    # 내려받기. PDF 는 보내는 용도(미리보기와 같다), Word 는 고치는 용도.
    # 탭마다 버튼이 있어 key 가 없으면 Streamlit 이 같은 버튼으로 본다.
    stem = f"{proposal_no(meta)}_{item.get('접근') or aid}_협업제안서"
    _, c1, c2, _ = st.columns([1, 2, 2, 1])
    c1.download_button("PDF 내려받기", data=files["pdf"], file_name=f"{stem}.pdf",
                       mime="application/pdf", type="primary",
                       use_container_width=True, key=f"pdf_{aid}")
    c2.download_button("Word 내려받기", data=files["docx"], file_name=f"{stem}.docx",
                       mime=("application/vnd.openxmlformats-officedocument"
                             ".wordprocessingml.document"),
                       use_container_width=True, key=f"docx_{aid}")
    st.markdown('<div style="text-align:center; color:#9CA3AF; font-size:0.8rem; margin-top:4px">'
                'PDF 는 보내는 용도, Word 는 문장을 고칠 때 씁니다.</div>', unsafe_allow_html=True)


def render_plan(item: dict, meta: dict) -> None:
    """
    안 하나. 화면은 요약 카드 하나와 제안서 미리보기 하나로 끝난다
    (시안 docs/ref/피그마_예시2.pdf). 매입가·역할·홍보 일정 같은 세부는
    화면에 두지 않고 제안서 문서에만 둔다 — 대표님은 여기서 어느 안을
    보낼지만 고르고, 내용은 문서로 본다.
    """
    approach = item.get("접근") or item.get("안_id") or ""
    aid = item.get("안_id") or "?"
    _, text_c, fill = TAB_COLOR.get(approach, ("#9CA3AF", "#374151", "#F3F4F6"))
    beer = item.get("페어링_맥주") or {}

    # 요약 카드 — 위 줄에 「제안안 #n  메뉴명」과 오른쪽 접근 배지, 아래에
    # 사진(왼쪽)과 선정 배경·메뉴 설명·판매가(오른쪽). 사진이 없으면 글이
    # 전체 폭을 쓴다. 바탕은 시안처럼 연한 회청색.
    st.markdown(
        f'<style>.st-key-card_{aid} {{ background:#F1F5F9; border-radius:12px; '
        f'padding:22px 26px 18px; }}'
        f'.st-key-card_{aid} [data-testid="stImage"] img {{ border-radius:10px; }}</style>',
        unsafe_allow_html=True)

    def block(title: str, body: str) -> str:
        return (f'<div style="margin:12px 0 3px; font-size:0.78rem; color:#64748B; '
                f'font-weight:700">{title}</div>'
                f'<div style="line-height:1.65; color:#1F2933">{body}</div>')

    body = ""
    if item.get("선정_사유"):
        body += block("선정 배경", end_dot(item["선정_사유"]))
    desc = item.get("구성") or ""
    if beer.get("메뉴명"):
        why = f" — {end_dot(beer['이유'])}" if beer.get("이유") else ""
        desc += f"<br>함께 내는 맥주: {beer['메뉴명']}{why}"
    body += block("메뉴 설명", desc)
    price = item.get("판매가_제안")
    listed = item.get("정가_합")
    if price and listed:
        body += block("바틀링 판매가", f"<b>{price:,}원</b> <span style='color:#94A3B8'>"
                                     f"(따로 사면 {listed:,}원)</span>")
    elif price:
        body += block("바틀링 판매가", f"<b>{price:,}원</b>")

    # 접근 배지를 제목 왼쪽에 둔다 (9/21 — 「제안안 #n」 자리에 배지).
    # 오른쪽 끝에 「보관함에 담기」. 여러 개 담을 수 있다.
    with st.container(key=f"card_{aid}"):
        c_head, c_pick = st.columns([4, 1], vertical_alignment="center")
        c_head.markdown(
            f'<div style="display:flex; align-items:center; gap:12px">'
            f'<span style="background:{fill}; color:{text_c}; padding:3px 12px; border-radius:8px; '
            f'font-size:0.78rem; font-weight:700; white-space:nowrap">{approach} 제안</span>'
            f'<span style="font-size:1.25rem; font-weight:700; flex:1">'
            f'{item.get("메뉴명") or "이름 없음"}</span></div>',
            unsafe_allow_html=True)
        # 체크박스는 글씨가 작아 눈에 안 띈다(9/25). 담긴 상태에 따라 글자와 색이
        # 바뀌는 버튼으로 둔다 — 누르면 담고, 다시 누르면 뺀다.
        # 스타일은 Streamlit 기본 primary/secondary 를 쓴다. 상태마다 CSS 를 주입하면
        # 그 markdown 이 빈 블록으로 공간을 차지해 카드가 흔들린다 (9/25).
        picked = aid in (meta.get("adopted") or [])
        if c_pick.button("담김 ✓" if picked else "보관함에 담기",
                         type="primary" if picked else "secondary",
                         key=f"adopt_{aid}", use_container_width=True):
            ids = set(meta.get("adopted") or [])
            ids.symmetric_difference_update({aid})
            if save_adopted(meta.get("plan_id"), sorted(ids)):
                meta["adopted"] = sorted(ids)
                # 알림은 rerun 하면 사라지므로 세션에 남겼다가 다시 그릴 때 띄운다.
                # 담았는지 뺐는지를 같이 남긴다 — 문구가 달라야 한다.
                st.session_state[SS_TOAST] = (not picked, len(ids))
                st.rerun()
        img = item.get("메뉴_이미지")
        if img:
            c_img, c_txt = st.columns([2, 3], gap="large")
            c_img.image(img, use_container_width=True)
            c_txt.markdown(body, unsafe_allow_html=True)
        else:
            st.markdown(body, unsafe_allow_html=True)

    render_proposal(item, meta)


def render_result(result: dict, meta: dict) -> None:
    # 자동 검사에 걸린 것과 되감기 기록은 화면에 내보내지 않는다.
    #
    # "A: '협력사_정가' 없음" 같은 말은 만든 사람이 읽을 문구다.
    # 대표님께는 뜻이 없고, 노란 상자로 수십 개가 쌓이면 정작 봐야 할
    # 기획안을 가린다. 기록은 plans.auto_check 에 그대로 남는다.
    if result["error"]:
        st.info("기획안을 끝까지 만들지 못했습니다. 다시 생성해 주세요.")

    final = result["final"]
    if not final:
        return

    plans = final.get("안") or []
    excluded = final.get("제외") or []

    for e in excluded:
        st.warning(f"{e.get('안_id')}안 제외 — {e.get('제외_사유')}")

    if not plans:
        st.error("안이 비어 있습니다. 다시 생성해 주세요.")
        return

    # 담기 버튼의 높이·글씨를 여기서 한 번에 정한다. 카드 안에서 상태마다 CSS 를
    # 주입하면 그 markdown 이 빈 블록으로 공간을 차지해 카드가 흔들린다 (9/25).
    st.markdown(
        '<style>' + ", ".join(f'.st-key-adopt_{a} button' for a in "ABC")
        + ' { min-height: 46px; font-size: 0.95rem; font-weight: 700; }</style>',
        unsafe_allow_html=True)

    # 담긴 목록은 따로 띄우지 않는다. 담을 때 알림이 뜨고, 카드마다 버튼이 「담김」
    # 으로 바뀌어 있어 무엇이 담겼는지 그 자리에서 보인다 (9/26).

    # 순위가 아니라 접근으로 가른다. 단품·세트·포장은 구성이 달라 우열이 없고,
    # 어느 것을 할지는 대표님이 정하신다. 탭마다 제안서가 붙는다.
    # 탭 버튼을 파일철 탭처럼 만든다. 세 탭을 간격 없이 붙이고, 테두리는
    # 위·오른쪽만 남겨 오른쪽 위만 둥글게 — 맨 왼쪽 탭은 왼쪽이 열린 모양이다.
    # 라벨엔 HTML 이 안 들어가 글자 일부만 꾸밀 수 없어서 버튼 전체에 색을 준다.
    # 고른 탭은 색을 채우고, 나머지는 연한 색 바탕.
    # 브라우저 탭 모양. 세 탭을 간격 없이 붙이고 위·오른쪽 테두리만 남겨
    # 오른쪽 위를 둥글게 한다. 뒤 탭을 8px 왼쪽으로 당겨 앞 탭의 둥근 모서리
    # 아래로 겹쳐 넣고(왼쪽 패딩으로 보정), z-index 를 앞에서부터 낮춰 앞 탭이
    # 위에 그려지게 한다 — 윗선이 끊기지 않는다. 탭 아래에 가로 구분선.
    # 배경은 선택 여부로만 가른다(회색/진회색). 카테고리 색은 테두리와 배지에만.
    # 라벨엔 HTML 이 안 들어가서 배지는 각 탭의 p::before 로 그린다.
    css = (
        '[data-baseweb="tab-list"] { display: flex; gap: 0; background: transparent;'
        '  padding: 0; border-bottom: 2px solid #9C9A94; }'
        '[data-baseweb="tab-list"] button { flex: 1 1 0; min-width: 0; position: relative;'
        '  justify-content: center; padding: 22px 20px; margin: 0;'
        '  border-left: none; border-bottom: none; border-radius: 0 16px 0 0;'
        '  background: #E1E4EB; }'
        # 마우스를 올리면 기본 테마가 반투명 색을 덧씌운다 — 배경을 그대로 고정
        '[data-baseweb="tab-list"] button:hover { background: #E1E4EB; }'
        '[data-baseweb="tab-list"] button[aria-selected="true"],'
        '[data-baseweb="tab-list"] button[aria-selected="true"]:hover { background: #FFFFFF; }'
        '[data-baseweb="tab-list"] button p { display: block; width: 100%; text-align: center;'
        '  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;'
        '  font-size: 14px; font-weight: 400; color: #8A8F99; margin: 0; }'
        '[data-baseweb="tab-list"] button[aria-selected="true"] p { color: #111827; font-weight: 700; }'
        '[data-baseweb="tab-list"] button p::before { display: inline-block; margin-right: 10px;'
        '  font-size: 12px; padding: 3px 8px; border-radius: 6px; font-weight: 600;'
        '  vertical-align: middle; }'
        "[data-baseweb='tab-highlight'] { display: none; }"
    )
    # 테두리는 셋 다 같은 회색. 카테고리 색은 배지에만 (9/20).
    n = len(plans)
    for i, p in enumerate(plans, 1):
        _, text, fill = TAB_COLOR.get(p.get("접근"), ("#9CA3AF", "#374151", "#F3F4F6"))
        label = p.get("접근") or p.get("안_id") or ""
        overlap = "margin-left: -16px; padding-left: 36px;" if i > 1 else ""
        css += (
            f'[data-baseweb="tab-list"] button:nth-child({i}) {{ z-index: {n - i + 1}; {overlap}'
            f'  border-top: 3px solid #9C9A94; border-right: 3px solid #9C9A94; }}'
            f'[data-baseweb="tab-list"] button:nth-child({i}) p::before {{'
            f'  content: "{label}"; background: {fill}; color: {text}; }}'
        )
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    tabs = st.tabs([p.get("메뉴명") or p.get("안_id") for p in plans])
    for tab, item in zip(tabs, plans):
        with tab:
            # 탭 내용을 상자로 감싼다. Streamlit 상자는 테두리 색을 따로 못 주니
            # 색은 안쪽 배지(render_plan)가 낸다.
            with st.container(border=True):
                render_plan(item, meta)

    with st.expander("검수 결과"):
        rows = final.get("체크리스트") or []
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        fixes = final.get("수정_내역") or []
        if fixes:
            st.markdown("**수정 내역**")
            for f in fixes:
                st.write(f"- {f}")

    with st.expander("생성 조건"):
        st.write(f"협력사 **{meta['partner_name']}** · **{meta['round']}차** · 실행일 "
                 f"**{meta['target_date']}** · {result['latency_ms']/1000:.1f}초")
        st.caption(f"프롬프트 버전 {meta.get('prompt_version') or '확인 불가'} · "
                   f"저장 id {meta.get('plan_id') or '저장 안 됨'}")
        st.text_area("컨텍스트 원문", meta["context"], height=240,
                     disabled=True, label_visibility="collapsed")

    # 채택 / 폐기(T23)는 아직 없다. 미구현 안내를 화면에 두지 않는다.


# ══════════════════════════════════════════
# 보관함
# ══════════════════════════════════════════

ARCHIVE_CSS = """
<style>
  /* 안내 띠 — 시안의 연한 파란 박스 */
  .arch-note { display:flex; align-items:center; justify-content:space-between;
    gap:16px; background:#EFF6FF; border:1px solid #DBEAFE; border-radius:12px;
    padding:18px 22px; margin:18px 0 26px; }
  .arch-note-l { color:#1F2933; font-size:15px; }
  .arch-note-l b { color:#2563EB; }
  .arch-note-r { color:#64748B; font-size:13px; }

  /* 표 머리 — 본문과 같은 열 비율로 그린다 (ARCH_COLS) */
  .st-key-arch_head { border:1px solid #E5E7EB; border-bottom:none;
    border-radius:14px 14px 0 0; background:#F8FAFC; }
  .st-key-arch_head [data-testid="stHorizontalBlock"] { padding:14px 22px; }
  .arch-head-cell { color:#64748B; font-size:13px; font-weight:700; }

  /* 행 */
  .st-key-arch_rows { border:1px solid #E5E7EB; border-top:none;
    border-radius:0 0 14px 14px; background:#FFFFFF; padding:0; }
  .st-key-arch_rows [data-testid="stHorizontalBlock"] {
    border-bottom:1px solid #F1F5F9; padding:18px 22px; margin:0; }
  .st-key-arch_rows [data-testid="stHorizontalBlock"]:last-child {
    border-bottom:none; }

  .arch-no { color:#0F172A; font-size:26px; font-weight:800; line-height:1.1; }
  .arch-no span { display:block; color:#94A3B8; font-size:12px; font-weight:600;
    margin-top:4px; }
  /* 회차 배지. 1차와 2차는 뜻이 달라 색도 달라야 한다 — 고를 수 있는 것은
     1차뿐이고 2차는 그것으로 만든 확정본이다 */
  .arch-rnd { display:inline-block; padding:5px 13px; border-radius:999px;
    background:#EEF2FF; color:#4338CA; font-size:14px; font-weight:800; }
  .arch-rnd-2 { background:#FEF3C7; color:#92400E; }

  /* 보낸 안으로 확정한 줄 — 눈에 띄어야 한다 */
  .st-key-arch_rows [data-testid="stHorizontalBlock"]:has(.arch-sent) {
    background:#F0FDF4; box-shadow:inset 3px 0 0 #16A34A; }
  .arch-sent-tag { display:inline-block; margin-left:8px; padding:3px 11px;
    border-radius:999px; background:#16A34A; color:#FFFFFF; font-size:12px;
    font-weight:700; vertical-align:middle; }

  /* 미리보기 — 「기획안 최적 생성 시작」과 같은 파란 버튼 */
  .st-key-arch_rows [data-testid="stHorizontalBlock"] .stButton button {
    height:38px; font-weight:700; }
  .arch-title { color:#0F172A; font-size:17px; font-weight:800; }
  .arch-tag { display:inline-block; margin-left:10px; padding:3px 11px;
    border-radius:999px; background:#ECFDF5; color:#047857; font-size:12px;
    font-weight:700; vertical-align:middle; }
  .arch-sub { color:#475569; font-size:14px; margin-top:6px; }
  .arch-meta { color:#94A3B8; font-size:13px; margin-top:8px; }
  .arch-meta span { margin-right:18px; }

  .arch-foot { display:flex; justify-content:space-between; color:#94A3B8;
    font-size:13px; margin-top:16px; }

  /* 하단 가운데 「최종 선택」 — 「기획안 최적 생성 시작」과 같은 모양 */
  .st-key-arch_pick_btn button { height:46px; font-weight:700; }
</style>
"""


# 보관함 표의 열 비율. 머리와 본문이 같은 값을 써야 글자가 제 열 위에 선다.
ARCH_COLS = [0.5, 0.8, 0.9, 5, 1.3, 1.4]
ARCH_HEAD = ["선택", "회차", "순서", "기획안 정보", "미리보기", "폼 링크"]


def form_link(partner: dict) -> str | None:
    """
    이 협력사의 초대 코드가 미리 채워진 「협의 사항 입력폼」 주소.

    손으로 적다 틀리는 것을 막는다. 코드가 어긋나면 폼은 통과시키고(형식만
    본다) .gs 가 맞는 협력사를 못 찾아 아무것도 저장하지 않는다 — 제출은
    됐는데 DB 에 없는 상태가 된다.

    설정이 없거나 협력사에 초대 코드가 없으면 None 을 돌려준다. 화면이 그
    사실을 알린다 — 조용히 빈 링크를 내놓으면 안 된다.
    """
    code = partner.get("invite_code")
    if not (PARTNER_FORM_URL and PARTNER_FORM_CODE_ENTRY and code):
        return None
    return (f"{PARTNER_FORM_URL}?usp=pp_url"
            f"&{PARTNER_FORM_CODE_ENTRY}={quote(code)}")


def _only_one(key: str, keys: list[str]) -> None:
    """
    보관함 체크는 하나만. 두 번째를 켜면 되돌리고 창을 띄운다.

    체크박스의 on_change 로 부른다. 위젯이 만들어진 **뒤에는** 그 세션 값을
    바꿀 수 없어 StreamlitAPIException 이 난다. 콜백은 다시 그리기 전에 돌아
    그때는 고칠 수 있다.

    해제는 그냥 둔다 — 고른 것을 무르는 동작이다.
    """
    if not st.session_state.get(f"arch_{key}"):
        return
    if any(st.session_state.get(f"arch_{k}") for k in keys if k != key):
        st.session_state[f"arch_{key}"] = False
        st.session_state[SS_ARCHIVE_WARN] = True


@st.dialog("하나만 고를 수 있습니다")
def _one_only() -> None:
    st.write("협력사에 보낼 안은 하나입니다. 먼저 고른 것을 두고 "
             "새로 고른 것은 해제했습니다.")
    if st.button("확인", type="primary", use_container_width=True):
        st.rerun()


@st.dialog("제안서 미리보기", width="large")
def _preview(o: dict, partner: dict) -> None:
    """
    보관함에서 제안서를 열어 본다. 생성 화면의 미리보기와 같은 문서다.

    저장된 기획안을 다시 보는 길이 여기 하나로 모인다. 그래서 「폼을 받은 뒤
    1차는 보기만」을 위한 별도 화면을 두지 않는다 (쟁점 1-3-1).
    """
    meta = {"partner_name": partner["name"], "round": o["round"],
            "target_date": o["target_date"], "plan_id": o["plan_id"],
            "takeout": partner.get("takeout")}
    missing = missing_fields(o["item"])
    if missing:
        st.warning(f"이 안에는 {', '.join(missing)}이(가) 없어 "
                   f"제안서를 만들 수 없습니다.")
        return

    with st.spinner("저장된 안을 불러오는 중..."):
        files = _proposal_files(o["item"], meta, cache_key=f"arch-{o['key']}")

    pages = files["pages"]
    slot = f"archpage_{o['key']}"
    idx = max(0, min(st.session_state.get(slot, 0), len(pages) - 1))

    # st.rerun() 을 부르지 않는다. 그것이 대화상자를 닫는다.
    # 대화상자는 다시 그려도 열린 채로 남는다 — 닫히는 것은 X 를 누를 때다.
    c_l, c_mid, c_r = st.columns([1, 7, 1], vertical_alignment="center")
    if c_l.button("‹", key=f"aprev_{o['key']}", disabled=idx == 0):
        st.session_state[slot] = idx - 1
    if c_r.button("›", key=f"anext_{o['key']}", disabled=idx >= len(pages) - 1):
        st.session_state[slot] = idx + 1
    c_mid.image(pages[idx], use_container_width=True)
    st.markdown(f'<div style="text-align:center; color:#9CA3AF; font-size:0.75rem">'
                f'Page {idx + 1} of {len(pages)}</div>', unsafe_allow_html=True)

    stem = f"{proposal_no(meta)}_{o['접근'] or o['안_id']}_협업제안서"
    c1, c2 = st.columns(2)
    c1.download_button("PDF 내려받기", data=files["pdf"], file_name=f"{stem}.pdf",
                       mime="application/pdf", type="primary",
                       use_container_width=True, key=f"apdf_{o['key']}")
    c2.download_button("Word 내려받기", data=files["docx"], file_name=f"{stem}.docx",
                       mime=("application/vnd.openxmlformats-officedocument"
                             ".wordprocessingml.document"),
                       use_container_width=True, key=f"adocx_{o['key']}")


@st.dialog("협의용 폼 링크")
def _form_link(partner: dict) -> None:
    """보낸 안을 정한 뒤, 협의 자리에서 함께 채울 폼 주소를 꺼내 준다."""
    link = form_link(partner)
    if not link:
        st.warning("폼 링크가 아직 준비되지 않았습니다.")
        st.write("링크를 만들려면 폼 주소를 한 번 등록해 두어야 합니다. "
                 "개발 쪽에 알려 주시면 바로 됩니다.")
        return

    st.write(f"**{partner['name']}** 과 협의하여 채울 폼입니다. "
             f"오른쪽 끝을 누르면 복사됩니다.")
    st.code(link, language=None, wrap_lines=True)
    st.caption("맨 위 「확인 코드」 칸은 이미 채워져 있습니다. 그 칸을 "
               "지우거나 고치면 안됩니다. ")
    st.write("")
    if st.button("기획안 생성으로 돌아가기", type="primary",
                 use_container_width=True):
        del st.query_params[ARCHIVE_PARAM]
        st.rerun()


@st.dialog("보낸 안을 바꿀까요?")
def _confirm_swap(old: dict, new: dict, partner_id: int) -> None:
    """
    이미 확정한 보낸 안이 있는데 다른 것을 고를 때 묻는다.

    보낸 안은 협력사에게 실제로 내민 것이라 바꾸면 2차의 메뉴가 통째로
    달라진다. 누르면 바로 바뀌는 것보다 한 번 확인하는 편이 맞다.
    """
    st.write(f"지금은 **{old['메뉴명']}** 로 되어 있습니다.")
    st.write(f"**{new['메뉴명']}** 로 바꾸시겠습니까?")
    c1, c2 = st.columns(2)
    if c1.button("바꾸기", type="primary", use_container_width=True):
        st.session_state.pop(SS_ARCHIVE_SWAP, None)
        if save_sent(partner_id, new["plan_id"], new["안_id"]):
            st.session_state[SS_ARCHIVE_NOTE] = (
                f"{new['메뉴명']} 로 바꿨습니다 — 그 줄에서 폼 링크를 받으세요")
        st.rerun()
    if c2.button("그대로 두기", use_container_width=True):
        st.session_state.pop(SS_ARCHIVE_SWAP, None)
        st.rerun()


def render_archive(partner: dict, options: list[dict]) -> None:
    """
    보관함 — 담아 둔 안을 보고 그중 하나를 「보낸 안」으로 확정한다.

    협력사를 고르는 칸을 두지 않는다. 기획안 생성 화면에서 고른 그 협력사의
    것만 보여주고, 바꾸려면 상단 내비로 돌아간다. 화면이 하나 더 늘면 「지금
    어느 협력사를 보고 있나」를 두 곳에서 관리하게 된다.

    담는 것은 여럿이고 보내는 것은 하나다 (쟁점 1-1-2). 그래서 체크는 하나만
    된다 — 두 번째를 고르면 되돌리고 창을 띄운다.
    """
    st.markdown(ARCHIVE_CSS, unsafe_allow_html=True)
    page_header("보관함", "담아 둔 기획안을 저장한 순서대로 보여줍니다.")

    if not options:
        st.info("아직 담은 안이 없습니다.")
        return

    st.markdown(
        f'<div class="arch-note">'
        f'<div class="arch-note-l">{partner["name"]}와의 협업기획안 '
        f'<b>{len(options)}개</b>가 저장되어 있습니다.</div>'
        f'<div class="arch-note-r">협력사에 보낼 안 하나를 골라 주세요. '
        f'그 안으로 2차 기획안을 만듭니다.</div></div>',
        unsafe_allow_html=True)

    # 머리도 본문과 같은 열 비율로 그린다. HTML 로 따로 그리면 st.columns 의
    # 폭과 맞지 않아 글자가 왼쪽에 몰린다.
    with st.container(key="arch_head"):
        for col, label in zip(st.columns(ARCH_COLS), ARCH_HEAD):
            col.markdown(f'<div class="arch-head-cell">{label}</div>',
                         unsafe_allow_html=True)

    sent = sent_pick(options)

    # 「최종 선택」으로 고르는 것은 협력사에게 **보낸** 안이라 1차뿐이다.
    # 그 안의 메뉴가 2차를 만드는 입력이 된다.
    #
    # 2차도 여러 번 돌려 담아 둘 수 있고 실제로 실행하는 것은 그중 하나인데,
    # 그 「실행할 안」은 아직 읽는 곳이 없다 — 실행 결과 기록(T23)이 붙을 때
    # 함께 만든다. 지금은 담기와 미리보기까지만 쓴다.
    keys = [o["key"] for o in options if o["round"] == 1]
    seq: dict[int, int] = {}        # 회차 안에서의 순서
    with st.container(key="arch_rows"):
        for o in options:
            seq[o["round"]] = seq.get(o["round"], 0) + 1
            is_sent = bool(sent and sent["key"] == o["key"])
            first = o["round"] == 1
            c_chk, c_rnd, c_no, c_body, c_btn, c_form = st.columns(
                ARCH_COLS, vertical_alignment="center")
            with c_chk:
                st.checkbox("선택", key=f"arch_{o['key']}",
                            label_visibility="collapsed", disabled=not first,
                            help=None if first else
                            "보낸 안은 1차에서 고릅니다. 2차는 그것으로 만든 "
                            "확정본이라 고를 대상이 아닙니다.",
                            on_change=_only_one, args=(o["key"], keys))
            with c_rnd:
                cls = "arch-rnd" if first else "arch-rnd arch-rnd-2"
                st.markdown(f'<div class="{cls}">{o["round"]}차</div>',
                            unsafe_allow_html=True)
            with c_no:
                st.markdown(f'<div class="arch-no">{seq[o["round"]]:02d}'
                            f'<span>저장 순서</span></div>',
                            unsafe_allow_html=True)
            with c_body:
                price = (f"판매가 {int(o['판매가_제안']):,}원"
                         if o.get("판매가_제안") else "판매가 미정")
                meta = [f"{o['접근']}안" if o["접근"] else f"{o['안_id']}안",
                        price]
                if o.get("target_date"):
                    meta.append(f"실행일 {o['target_date']}")
                # arch-sent 가 있으면 CSS 가 그 줄 배경과 왼쪽 띠를 바꾼다.
                mark = ('<span class="arch-sent arch-sent-tag">보낸 안</span>'
                        if is_sent else '')
                st.markdown(
                    f'<div class="arch-title">{o["메뉴명"]}{mark}</div>'
                    f'<div class="arch-sub">{end_dot(o["선정_사유"]) or ""}</div>'
                    f'<div class="arch-meta">'
                    + "".join(f"<span>{m}</span>" for m in meta)
                    + '</div>', unsafe_allow_html=True)
            with c_btn:
                if st.button("미리보기", key=f"apv_{o['key']}", type="primary",
                             use_container_width=True,
                             icon=":material/description:"):
                    _preview(o, partner)
            with c_form:
                # 폼 1 은 갈래가 정해지기 전에 채운다. 그래서 「보낸 안」이
                # 정해진 그 줄에 둔다.
                #
                # 2차 줄은 비운다. 폼 2 는 2차를 만들기 **전에** 채우는 것이라
                # 이미 만들어진 2차 줄에 붙이면 순서가 거꾸로다. 쓰는 갈래도
                # B/C 뿐이고, 그 자리는 메뉴를 확정하는 화면이다 (아직 없다).
                if first and st.button(
                        "폼 링크", key=f"afm_{o['key']}",
                        use_container_width=True, disabled=not is_sent,
                        icon=":material/link:",
                        help=None if is_sent else
                        "협력사에 보낸 안으로 고르면 열립니다."):
                    _form_link(partner)

    st.markdown('<div class="arch-foot">'
                '<div>보낸 안을 고르면 그 메뉴로 2차 기획안을 만듭니다.</div>'
                '<div>최근 저장한 순서 기준 · 최대 20개</div></div>',
                unsafe_allow_html=True)

    now = [k for k in keys if st.session_state.get(f"arch_{k}")]

    _, c_btn, _ = st.columns([3, 2, 3])
    with c_btn:
        with st.container(key="arch_pick_btn"):
            if st.button("최종 선택", type="primary", use_container_width=True,
                         icon=":material/check_circle:", disabled=not now):
                new = next(o for o in options if o["key"] == now[0])
                # 이미 확정한 것이 있고 다른 것을 골랐으면 한 번 묻는다.
                # 보낸 안을 바꾸면 2차의 메뉴가 통째로 달라진다.
                if sent and sent["key"] != new["key"]:
                    st.session_state[SS_ARCHIVE_SWAP] = new
                    st.rerun()
                # 여기서 화면을 닫지 않는다. 안을 고른 다음 할 일이 그 줄의
                # 「폼 링크」를 받는 것이라, 닫아 버리면 다시 들어와야 한다.
                # 생성 화면으로 돌아가는 일은 폼 링크 창이 맡는다.
                if save_sent(partner["id"], new["plan_id"], new["안_id"]):
                    st.session_state[SS_ARCHIVE_NOTE] = (
                        f"{new['메뉴명']} 로 정했습니다 — 그 줄에서 폼 링크를 "
                        f"받으세요")
                st.rerun()

    # 알림은 화면 맨 끝에서 그린다. 위에 두면 떴다 사라질 때마다 아래가 밀린다.
    # 담기 알림보다 길게 둔다 — 읽고 나서 다음에 할 일까지 적혀 있다.
    flash_note(st.session_state.pop(SS_ARCHIVE_NOTE, None), seconds=3.5)


# ══════════════════════════════════════════
# 화면
# ══════════════════════════════════════════

partners = load_partners()

# 파트너 추천에서 넘겨준 협력사가 목록에 없을 수 있다. 방금 등록한 것이면
# 목록 캐시(60초)에 아직 안 들어와 있다. 그때는 한 번만 다시 읽는다.
#
# 다시 읽어도 없으면 지워진 협력사다. 그 값을 버려야 한다 — 셀렉트박스에 없는
# 값이 남아 있으면 화면이 아예 뜨지 않는다.
_want = st.session_state.get(SS_PARTNER_ID)
if _want and not any(p["id"] == _want for p in partners):
    load_partners.clear()
    partners = load_partners()
    if not any(p["id"] == _want for p in partners):
        st.session_state.pop(SS_PARTNER_ID, None)
        st.session_state.pop("partner_pick", None)

# 상단 바를 여기서 그린다. 보관함 개수를 그 전에 세야 이번 실행에 반영된다 —
# 상단 바가 본문보다 먼저 그려지므로, 본문에서 세면 한 박자 늦게 바뀐다.
#
# 셀렉트박스 값("partner_pick")을 먼저 본다. 위젯 값은 다시 그리기가 시작될 때
# 이미 새 값으로 바뀌어 있어, 협력사를 바꾸는 그 실행에서 맞는 개수가 나온다.
# 보관함 화면에서는 그 위젯이 안 그려져 값이 지워지므로 SS_PARTNER_ID 로 받는다.
_in_archive = st.query_params.get(ARCHIVE_PARAM) == "1"
_pid = (st.session_state.get("partner_pick")
        or st.session_state.get(SS_PARTNER_ID)
        or (partners[0]["id"] if partners else None))
st.session_state[SS_ARCHIVE_COUNT] = (
    len(sent_options(load_archive(_pid))) if _pid else 0)

# 보관함 안에서는 보관함 버튼을 두지 않는다. 상단 내비로 돌아가면 된다.
apply_chrome("" if _in_archive else "archive")

st.markdown(EQUAL_HEIGHT_BOXES, unsafe_allow_html=True)

if not partners:
    st.title("기획안 생성")
    st.info("등록된 협력사가 없습니다. 파트너 추천에서 먼저 등록해 주세요.")
    st.stop()

labels = {p["id"]: f"{p['name']} ({p['category']})" for p in partners}

# 상단 「보관함」을 누르면 이 화면 대신 보관함이 뜬다.
#
# 협력사는 아래 셀렉트박스에서 고른 것을 그대로 쓴다(key="partner_pick").
# 보관함에 협력사 고르는 칸을 또 두면 「지금 어느 협력사를 보고 있나」를
# 두 곳에서 관리하게 된다.
if _in_archive:
    partner = next((p for p in partners if p["id"] == _pid), partners[0])
    options = sent_options(load_archive(partner["id"]))
    if st.session_state.pop(SS_ARCHIVE_WARN, False):
        _one_only()
    _swap = st.session_state.get(SS_ARCHIVE_SWAP)
    _old = sent_pick(options)
    if _swap and _old:
        _confirm_swap(_old, _swap, partner["id"])
    elif _swap:
        # 바꿀 대상이 사라졌다(무르기 등). 표시만 지운다.
        st.session_state.pop(SS_ARCHIVE_SWAP, None)
    render_archive(partner, options)
    st.stop()

# 입력부는 시안(docs/ref/피그마_예시2.pdf)의 흰 카드 모양이다. 문구는 시안
# 그대로 두었고 나중에 고친다 (9/21).
# 명세서 4-2 의 「희망 기간」 방식은 아직 없어 고르는 칸을 두지 않는다 (T45).
page_header("기획안 생성", "AI로 최적의 기획안을 빠르게 생성합니다.")
st.markdown(
    '<style>.st-key-param_card { background:#FFFFFF; border:1px solid #E5E7EB; '
    'border-radius:14px; padding:26px 30px 22px 20px; }'
    '.st-key-param_card label p { font-weight:700; color:#1F2933; }'
    '.st-key-param_card label p::after { content:" *"; color:#EF4444; }'
    # 협력사 셀렉트박스만 좁힌다. 열 폭은 그대로 두고 입력 칸의 최대 폭만 잡는다 —
    # 가장 긴 이름 「테스트용 제과점 (제과·디저트)」 이 한 줄에 들어오는 폭 (9/22).
    '.st-key-partner_box, .st-key-partner_box [data-testid="stSelectbox"],'
    ' .st-key-partner_box [data-baseweb="select"] { max-width: 280px !important; }'
    # 카드 왼쪽 여백 20px 에 아이콘. 입력 칸 줄은 아이콘 폭(26px)+간격(10px)만큼
    # 들여서 제목 글자·라벨이 같은 세로선에 서게 한다. 셀렉트박스는 안쪽 여백만큼
    # (10px) 왼쪽으로 당겨 상자 안 글자도 그 선에 맞춘다 (9/22).
    '.st-key-param_fields { padding-left: 36px; }'
    '.st-key-partner_box [data-baseweb="select"],'
    ' .st-key-param_fields [data-testid="stDateInput"] [data-baseweb="input"] { margin-left: -10px; }</style>',
    unsafe_allow_html=True)
with st.container(key="param_card"):
    st.markdown(
        '<div style="display:flex; align-items:center; gap:10px; margin:0 0 14px 0">'
        '<span style="background:#DBEAFE; color:#2563EB; border-radius:8px; width:26px; '
        'height:26px; display:inline-flex; align-items:center; justify-content:center">'
        '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2.2" stroke-linecap="round"><path d="M14 4l6 6-10 10-6-6z"/>'
        '<path d="M4 20l3-3M14 4l2-2M20 10l2-2"/></svg></span>'
        '<span style="font-weight:800; color:#0F172A">기획안 생성 조건 설정</span></div>',
        unsafe_allow_html=True)
    with st.container(key="param_fields"):
        c1, c2 = st.columns(2, gap="large")
        with c1:
            with st.container(key="partner_box"):
                # key 를 준다 — 보관함 화면이 이 값으로 어느 협력사인지 안다.
                #
                # index 로 기본값을 준다. 다른 화면에서 돌아오면 위젯 key 의 값이
                # 지워져 있어, 그것 없이는 늘 첫 협력사로 되돌아간다. 파트너
                # 추천에서 고른 협력사가 여기로 넘어오는 길이 이것이다.
                ids = list(labels)
                last = st.session_state.get(SS_PARTNER_ID)
                pid = st.selectbox("협업 제안 대상", ids,
                                   index=ids.index(last) if last in ids else 0,
                                   format_func=labels.get, key="partner_pick")
            chosen = next(p for p in partners if p["id"] == pid)
            st.session_state[SS_PARTNER_ID] = pid
            # 회차·협의 가능 시간·납품 요일 캡션은 화면에 두지 않는다 (9/22).
            # 회차는 결과의 「생성 조건」에 있고, 납품 요일은 체인 입력에 그대로 들어간다.
        with c2:
            target = st.date_input("협업 시작 희망일",
                                   value=datetime.now(KST).date() + timedelta(days=7))

        # 회차는 사람이 고른다. 전에는 폼 값이 있으면 무조건 2차로 떠서 1차 과정을
        # 보여줄 수 없었다 (9/24). 조건은 docs/private/쟁점_2차흐름과_폼_0925.md 1-3-1.
        #
        # 시연용 협력사(is_seed)는 전부 열어 둔다 — 폼 값은 있는데 채택 기록이 없어
        # 그대로 두면 1차도 2차도 못 만들고, 시연에서 두 과정을 다 보여줘야 한다.
        # 그 밖의 협력사는:
        #   1차  폼이 오기 전까지만. 폼이 왔다는 것은 제안서가 나갔다는 것이고,
        #        나갔다는 것은 이미 골랐다는 것이라 새로 만들 1차가 없다. 보기만 한다.
        #   2차  폼이 와야 하고, 1차에서 고른 안이 있어야 한다.
        form_in = has_form(chosen)
        picks = load_adopted(chosen["id"])
        seed = bool(chosen.get("is_seed"))
        # 시연용의 예외는 「1차 생성 잠금을 푼다」 하나뿐이다. 폼 값은 있는데 채택
        # 기록이 없어 그대로 두면 1차도 2차도 못 만든다. 한 번 만들어 안을 고르고
        # 나면 그 뒤로는 실제 협력사와 완전히 같은 화면이 된다 — 시연에서 "실제는
        # 다릅니다" 를 설명하지 않아도 되게 (9/25).
        can_1st = not form_in or seed
        can_2nd = form_in and bool(picks)

        # 회차는 고르게 하지 않는다. 두 회차가 동시에 가능한 적이 없어서다 —
        # 폼 전엔 1차만, 폼이 왔고 안까지 골랐으면 2차만이다.
        rnd = 2 if can_2nd else 1

        options = sent_options(picks)

        # 2차는 「어느 안으로 보냈나」를 알아야 만들 수 있다. 그 안의 메뉴가
        # 협업 메뉴다 — A 갈래는 폼이 메뉴 이름을 묻지 않아 여기서만 알 수 있다.
        #
        # 담긴 것이 하나여도 자동으로 정하지 않는다. 담기와 보내기는 다른
        # 행위이고(쟁점 1-1-2), 보내는 일은 화면 밖(메일·카톡)에서 일어나
        # 시스템이 알 수 없다. 자동으로 정하면 보낸 적 없는 안으로 2차가
        # 만들어진다.
        sent = sent_pick(options)

        # 갈래에 따라 2차를 막아야 할 수 있다. 막으면 왜 막았는지 적는다.
        blocked = menu_block(chosen) if rnd == 2 else None

        # 고른 안은 보관함에서 표시로 보인다. 여기에 또 적지 않는다.
        # 다만 안 골랐으면 생성 버튼이 막히므로 왜 막혔는지는 알려야 한다.
        if rnd == 2 and not sent:
            st.caption("상단 「보관함」에서 협력사에 보낼 안을 골라 주세요.")

    if blocked:
        st.warning(blocked)

    has_menus = bool(menu_rows(chosen))
    if not has_menus:
        st.info("메뉴·판매가가 아직 없습니다. 들어오면 만들 수 있습니다.")

    allowed = (can_1st if rnd == 1
               else (can_2nd and bool(sent) and not blocked))
    _, c_btn = st.columns([3, 1])
    go = c_btn.button("기획안 최적 생성 시작", type="primary", icon=":material/auto_awesome:",
                      use_container_width=True, disabled=not has_menus or not allowed)

if go:
    generate(chosen, target, rnd, sent)

# 생성 조건 상자와 결과 사이의 한 줄. 만드는 동안에는 이 자리를 진행 상황이
# 쓴다 (generate 의 st.status 가 "n차 기획안 생성 중..."). 끝난 뒤에 지금 상태와
# 다음에 할 일을 적는다. if/elif 라 맞는 것 하나만 나오므로 순서가 곧 해야 할 일의 순서다.
if not picks:
    st.caption("1차 기획안을 만듭니다. 안을 고르면 다음 단계로 넘어갑니다.")
elif not form_in:
    st.caption("협력사와 합의해 폼을 채우면 2차 기획안을 만들 수 있습니다.")
else:
    st.caption("폼을 받았습니다. 2차 기획안을 만듭니다. "
               "골랐던 1차 기획안은 보관함에서 다시 볼 수 있습니다.")

if st.session_state.get(SS_RESULT):
    meta = st.session_state[SS_META]
    n_plans = len((st.session_state[SS_RESULT].get("final") or {}).get("안") or [])
    st.markdown(
        f'<div style="margin:18px 0 6px; padding:14px 18px; border:1.5px solid #34D399; '
        f'background:#ECFDF5; border-radius:10px; color:#065F46; font-weight:700; '
        f'display:flex; align-items:center; gap:10px">'
        f'<span style="background:#059669; color:#fff; border-radius:50%; width:20px; height:20px; '
        f'display:inline-flex; align-items:center; justify-content:center; font-size:12px">✓</span>'
        f'분석 완료 - AI 기반 최적 제안 {n_plans}종이 도출되었습니다. '
        f'하단 탭을 통해 세부 제안과 문서를 검토해 보세요.</div>',
        unsafe_allow_html=True)
    render_result(st.session_state[SS_RESULT], meta)
elif not go:
    st.info("협력사와 실행일을 고르고 생성을 누르면 약 30초 뒤 기획안 3안이 나옵니다.")

# 담기·빼기 알림. 페이지 맨 끝에서 그린다 (flash_note 설명 참고).
flash = st.session_state.pop(SS_TOAST, None)
if flash is not None:
    added, n_picked = flash
    if added:
        msg = f"보관함에 담았습니다 — 모두 {n_picked}개"
    else:
        msg = (f"보관함에서 뺐습니다 — 남은 안 {n_picked}개" if n_picked
               else "보관함에서 뺐습니다 — 담긴 안이 없습니다")
    flash_note(msg)
