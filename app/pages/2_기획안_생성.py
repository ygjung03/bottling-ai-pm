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

import _path  # noqa: F401  (프로젝트 루트를 sys.path 에 추가)
import streamlit as st

from app.auth import require_owner
from app.proposal import (build_proposal_docx, build_proposal_pdf, end_dot,
                          missing_fields, pdf_pages, proposal_no)
from app.theme import apply_chrome
from app.ui import page_header
from chain.inputs import (BOTTLING_INGREDIENTS, BOTTLING_SNS, MARGIN_REF,
                          NO_TREND_MENU, PAST_CASES, WEATHER_PREF,
                          build_beer_list, build_constraints, build_events,
                          build_partner_blockers, build_partner_resources,
                          build_partner_sns, build_rec_reason)
from chain.runner import run
from context.builder import build as build_context
from db.client import get_client

st.set_page_config(page_title="기획안 생성", page_icon="📝", layout="wide",
                   initial_sidebar_state="collapsed")
require_owner()
apply_chrome()

KST = timezone(timedelta(hours=9))
SS_RESULT = "plan_result"      # 체인 출력
SS_META = "plan_meta"          # 협력사·날짜 등 생성 조건

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


def round_of(partner: dict) -> int:
    """
    1차인지 2차인지. 구글 폼이 채우는 값이 하나라도 있으면 2차다.

    폼에서 납품 요일과 제약은 필수라 제출했으면 반드시 있다. 메뉴·가격은
    1차에서 후기로 먼저 채우므로 회차의 근거가 되지 못한다.
    """
    filled = any(partner.get(k) for k in
                 ("available_slots", "blockers", "sns_channel"))
    return 2 if filled else 1


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
            # 2차가 어느 1차를 이어받았는지. 협의 결과를 넣어 다시 만드는
            # 구조가 붙으면 채운다. 지금은 회차만 남긴다.
            "prev_plan_id": None,
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


# ══════════════════════════════════════════
# 생성
# ══════════════════════════════════════════

def generate(partner: dict, target: date) -> None:
    """체인을 돌리고 결과를 세션에 남긴다."""
    with st.status("기획안 생성 중...", expanded=True) as box:
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
            partner_res=build_partner_resources(partner),
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
            on_step=on_step,
        )

        sec = result["latency_ms"] / 1000
        if result["error"]:
            box.update(label="기획안을 끝까지 만들지 못했습니다", state="error")
        else:
            box.update(label=f"완료 — {sec:.0f}초", state="complete")

    meta = {
        "partner_id": partner["id"],
        "partner_name": partner["name"],
        "round": round_of(partner),
        "target_date": target.isoformat(),
        "context": ctx,
        "prompt_version": prompt_version(),
    }
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


def _proposal_files(item: dict, meta: dict) -> dict:
    """
    안 하나의 제안서 파일 — docx, pdf, 페이지 이미지. 세션에 캐시한다.

    Word 변환이 안마다 5~8초라 화면이 다시 그려질 때마다 하면 안 된다.
    탭을 옮기거나 페이지를 넘길 때마다 스크립트가 다시 도는데, 그때는 여기서
    바로 꺼낸다. 캐시는 generate() 가 새 기획안을 만들 때 비운다.
    """
    cache = st.session_state.setdefault(SS_FILES, {})
    key = item.get("안_id")
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
    with st.container(key=f"card_{aid}"):
        st.markdown(
            f'<div style="display:flex; align-items:center; gap:12px">'
            f'<span style="background:{fill}; color:{text_c}; padding:3px 12px; border-radius:8px; '
            f'font-size:0.78rem; font-weight:700; white-space:nowrap">{approach} 제안</span>'
            f'<span style="font-size:1.25rem; font-weight:700; flex:1">'
            f'{item.get("메뉴명") or "이름 없음"}</span></div>',
            unsafe_allow_html=True)
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
# 화면
# ══════════════════════════════════════════

st.markdown(EQUAL_HEIGHT_BOXES, unsafe_allow_html=True)

partners = load_partners()
if not partners:
    st.title("기획안 생성")
    st.info("등록된 협력사가 없습니다. 파트너 추천에서 먼저 등록해 주세요.")
    st.stop()

labels = {p["id"]: f"{p['name']} ({p['category']})" for p in partners}

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
                pid = st.selectbox("협업 제안 대상", list(labels), format_func=labels.get)
            chosen = next(p for p in partners if p["id"] == pid)
            # 회차·협의 가능 시간·납품 요일 캡션은 화면에 두지 않는다 (9/22).
            # 회차는 결과의 「생성 조건」에 있고, 납품 요일은 체인 입력에 그대로 들어간다.
        with c2:
            target = st.date_input("협업 시작 희망일",
                                   value=datetime.now(KST).date() + timedelta(days=7))

    has_menus = bool(chosen.get("menu_prices"))
    if not has_menus:
        st.info("메뉴·판매가가 아직 없습니다. 들어오면 만들 수 있습니다.")

    _, c_btn = st.columns([3, 1])
    go = c_btn.button("기획안 최적 생성 시작", type="primary", icon=":material/auto_awesome:",
                      use_container_width=True, disabled=not has_menus)

if go:
    generate(chosen, target)

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
