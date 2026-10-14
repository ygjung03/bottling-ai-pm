"""
관리 — 개발팀 및 이관 대비

프롬프트를 코드에서 분리해 비개발자가 수정할 수 있게 한다. 
"""
import _path
import re
from datetime import datetime, timedelta, timezone

import altair as alt
import pandas as pd
import streamlit as st

from app.auth import require_owner
from app.theme import apply_chrome
from config.settings import KRW_PER_USD, USAGE_LOG_FROM
from db import api_usage as usage
from db.api_usage import KST
from db.client import get_client

# 배포는 UTC 라 그냥 today() 를 쓰면 새벽에 하루 전 날짜가 들어간다. 이 날짜가
# 맥주를 올리고 내린 날로 DB 에 남아, 지난 라인업을 되짚는 근거가 된다
# (scripts/update_beers.py 와 같은 이유).
KST = timezone(timedelta(hours=9))

st.set_page_config(page_title="관리", page_icon="⚙️", layout="wide",
                   initial_sidebar_state="collapsed")
require_owner()
apply_chrome()

st.title("관리")
st.caption("판매 중인 맥주 라인업과 AI 사용량을 확인합니다.")

# 프롬프트·제약조건 탭은 뺐다 (10/15). 둘 다 「구현 예정」 안내만 띄우는
# 껍데기였고, 밖으로 나가는 보고서에도 적혀 있지 않다. 명세서 8-1 의 이관
# 설계에만 있던 것이라 그 표도 함께 고쳤다.
tab_beer, tab_usage = st.tabs(["맥주 라인업", "API 사용량"])

# ───────────────────────── 맥주 라인업 (T10b) ─────────────────────────
#
# 예시 화면: docs/ref/맥주 라인업 화면_피그마.pdf · 계획: docs/W5-최종마감_작업계획.md A-2
#
# [지우지 않고 내린다]
#   X 는 행을 지우지 않고 valid_to 에 오늘 날짜를 넣는다. 지우면 그 맥주로 만든 지난
#   기획안을 되짚을 수 없다 (scripts/update_beers.py 와 같은 방식). 기획안 생성은
#   valid_to 가 비어 있는 것만 읽는다 (chain/inputs.build_beer_list).
#
# [화면에서 넣은 값이 그대로 AI 에 들어간다]
#   - 바틀링 라거 / 12원/ml / 라거 / 4.5도 / 가벼움, 탄산감 있음 [고정]
#   도수 0 은 논알콜로 적히고 페어링에서 빠진다.

SS_BEER_ADD = "beer_add_open"
SS_BEER_NOTE = "beer_note"

# 표를 시안만큼 촘촘하게 만드는 것.
#
# [줄 사이 선을 요소로 두지 않는다]
#   st.divider() 는 위아래 여백이 커서 행이 늘어진다. 그렇다고 얇은 선을
#   st.markdown 으로 그려 넣으면 그 요소가 **16px 을 차지한다** — 빈 요소가
#   그보다 작아지지 않는 것을 재서 확인했다. 그래서 선은 요소가 아니라 행
#   상자의 윗 테두리로 그린다.
#
# [상자 이름으로 잡는다]
#   st.container(key=...) 를 쓰면 그 상자에 `st-key-<이름>` 이 붙는다. 상단
#   내비게이션이 이미 쓰는 방식이다 (app/theme.py). 행마다 id 가 달라 앞부분만
#   맞춘다.
BEER_CSS = """
<style>
/* 행 사이에 Streamlit 이 16px 을 넣는다. 그만큼 벌어지면 시안보다 성겨진다 */
.st-key-beer_rows { gap: 0 !important; }
div[class*="st-key-beer_row_"] {
    border-top: 1px solid #F1F2F4;
    padding: 6px 0;
}
/* 「＋ 맥주 추가」 — 시안의 파란 글씨·파란 테두리 */
.st-key-beer_add_row { border-top: 1px solid #F1F2F4; padding-top: 10px; }
.st-key-beer_add_btn button {
    color: #2563EB !important;
    border: 1px solid #2563EB !important;
    background: #FFFFFF !important;
    font-weight: 700 !important;
}
.st-key-beer_add_btn button:hover { background: #EFF4FF !important; }
</style>
"""


def load_lineup() -> list[dict]:
    """판매 중(valid_to 가 빈) 맥주. 고정 메뉴 먼저, 그다음 싼 순."""
    return (get_client().table("beers").select("*")
            .is_("valid_to", "null")
            .order("is_fixed", desc=True).order("price_per_ml")
            .execute().data or [])


def split_notes(text: str) -> list[str]:
    """「감귤 향 · 산뜻함, 부드러운 밀」 → ["감귤 향", "산뜻함", "부드러운 밀"]"""
    return [t.strip() for t in re.split(r"[·,，、/]", text or "") if t.strip()]


def _num(v) -> str:
    f = float(v)
    return str(int(f)) if f.is_integer() else f"{f:g}"


@st.dialog("판매 종료")
def confirm_retire(beer: dict) -> None:
    st.markdown(f"**{beer['name']}**을(를) 현재 라인업에서 내릴까요?")
    st.caption("기록은 지우지 않습니다. 이 맥주로 만든 지난 기획안은 그대로 남고, "
               "앞으로 만드는 기획안에서만 빠집니다.")
    if beer.get("is_fixed"):
        st.warning("고정 메뉴로 표시된 맥주입니다.")
    c1, c2 = st.columns(2)
    if c1.button("취소", use_container_width=True):
        st.rerun()
    if c2.button("내리기", type="primary", use_container_width=True):
        try:
            (get_client().table("beers")
             .update({"valid_to": datetime.now(KST).date().isoformat()})
             .eq("id", beer["id"]).execute())
            st.session_state[SS_BEER_NOTE] = f"'{beer['name']}'을(를) 라인업에서 내렸습니다."
        except Exception as e:
            st.session_state[SS_BEER_NOTE] = f"내리지 못했습니다 — {e}"
        st.rerun()


def render_add_form(names: set[str]) -> None:
    with st.form("beer_add_form", clear_on_submit=False, border=True):
        top_l, top_r = st.columns([3, 2])
        top_l.markdown("**새 맥주 추가**")
        top_r.caption("다섯 항목을 모두 입력해 주세요. 논알콜은 도수 0.")
        c = st.columns([2.2, 1.2, 1.6, 1, 3.4])
        name = c[0].text_input("맥주 이름", placeholder="성수 세션 IPA")
        price = c[1].number_input("ml당 가격 (원/ml)", min_value=0.0, max_value=999.0,
                                  value=None, step=1.0, placeholder="18")
        style = c[2].text_input("스타일", placeholder="세션 IPA")
        abv = c[3].number_input("도수 (%)", min_value=0.0, max_value=20.0,
                                value=None, step=0.1, format="%.1f", placeholder="4.5")
        notes = c[4].text_input("맛 특성", placeholder="자몽 향 · 가벼운 바디 · 산뜻한 쓴맛",
                                help="· 또는 쉼표로 나눕니다. 페어링의 실제 근거가 됩니다.")
        fixed = st.checkbox("고정 메뉴 (월 교체 대상이 아님)", value=False)

        b = st.columns([6, 1, 1])
        b[0].caption("'추가'를 누르면 현재 라인업에 등록됩니다.")
        cancel = b[1].form_submit_button("취소", use_container_width=True)
        add = b[2].form_submit_button("＋ 추가", type="primary", use_container_width=True)

    if cancel:
        st.session_state[SS_BEER_ADD] = False
        st.rerun()
    if not add:
        return

    name, style, flavor = (name or "").strip(), (style or "").strip(), split_notes(notes)
    # 중복을 먼저 본다. 이름만으로 알 수 있는 것이라, 다섯 칸을 다 채우고 나서야
    # 「이미 있습니다」를 듣게 하면 채운 것이 헛일이 된다.
    if name.lower() in names:
        st.error(f"'{name}'은(는) 이미 판매 중인 라인업에 있습니다.")
        return
    missing = [label for label, ok in (("맥주 이름", name), ("ml당 가격", price),
                                       ("스타일", style), ("도수", abv is not None),
                                       ("맛 특성", flavor)) if not ok]
    if missing:
        st.error("비어 있는 항목: " + ", ".join(missing))
        return

    try:
        get_client().table("beers").insert({
            "name": name, "price_per_ml": float(price), "style": style,
            "abv": float(abv), "flavor_notes": flavor,
            "is_alcohol": float(abv) > 0, "is_fixed": fixed,
            "valid_from": datetime.now(KST).date().isoformat(), "valid_to": None,
        }).execute()
    except Exception as e:
        st.error(f"등록하지 못했습니다 — {e}")
        return
    st.session_state[SS_BEER_ADD] = False
    st.session_state[SS_BEER_NOTE] = f"'{name}'을(를) 라인업에 추가했습니다."
    st.rerun()


def render_lineup() -> None:
    note = st.session_state.pop(SS_BEER_NOTE, None)
    if note:
        st.toast(note)

    try:
        beers = load_lineup()
    except Exception as e:
        st.error(f"맥주 라인업을 불러오지 못했습니다 — {e}")
        return

    with st.container(border=True):
        # 시안처럼 제목과 같은 줄, 카드 오른쪽 끝에 붙인다. st.caption 은 칸
        # 왼쪽에서 시작해 가운데 띄엄하게 놓인다.
        h1, h2 = st.columns([3, 2], vertical_alignment="center")
        h1.markdown(BEER_CSS +
                    f"#### 현재 맥주 라인업 &nbsp;<span style='font-size:0.8rem;"
                    f"background:#EEF0F3;padding:2px 8px;border-radius:6px'>{len(beers)}종</span>",
                    unsafe_allow_html=True)
        h2.markdown('<div style="text-align:right; color:#6B7280;'
                    ' font-size:0.85rem">✕ 판매를 종료한 맥주는 오른쪽 ✕로'
                    ' 라인업에서 내리세요.</div>', unsafe_allow_html=True)

        widths = [2.4, 1.1, 1.6, 0.8, 3.4, 0.6]
        head = st.columns(widths)
        for col, label in zip(head, ["맥주 이름", "ml당 가격", "스타일", "도수", "맛 특성", "내리기"]):
            col.caption(label)

        if not beers:
            st.caption("판매 중인 맥주가 없습니다. 아래에서 추가해 주세요.")
        rows_box = st.container(key="beer_rows")
        for b in beers:
            # 줄 사이 선은 st.divider() 가 아니라 행 상자의 윗 테두리로 그린다
            # (BEER_CSS 설명 참고).
            with rows_box, st.container(key=f"beer_row_{b['id']}"):
                row = st.columns(widths, vertical_alignment="center")
                tag = " &nbsp;<span style='font-size:0.72rem;color:#2F6FE0;background:#EAF2FE;" \
                      "padding:1px 6px;border-radius:4px'>고정</span>" if b.get("is_fixed") else ""
                row[0].markdown(f"**{b['name']}**{tag}", unsafe_allow_html=True)
                row[1].markdown(f"{_num(b['price_per_ml'])} <span style='color:#6B7280'>원/ml</span>",
                                unsafe_allow_html=True)
                row[2].markdown(b.get("style") or "—")
                abv = b.get("abv")
                row[3].markdown("—" if abv is None else ("논알콜" if float(abv) == 0 else f"{_num(abv)} %"))
                row[4].markdown(" · ".join(b.get("flavor_notes") or []) or "—")
                if row[5].button("✕", key=f"beer_del_{b['id']}", help="라인업에서 내리기"):
                    confirm_retire(b)

        with st.container(key="beer_add_row"):
            if not st.session_state.get(SS_BEER_ADD):
                a1, a2 = st.columns([1, 5], vertical_alignment="center")
                if a1.button("＋ 맥주 추가", key="beer_add_btn", use_container_width=True):
                    st.session_state[SS_BEER_ADD] = True
                    st.rerun()
                a2.caption("월 1회 교체되는 맥주를 여기서 넣고 내립니다.")
            else:
                render_add_form({(b["name"] or "").strip().lower() for b in beers})

    # 「비면 페어링이 추측으로 채워집니다」는 지웠다. 추가 폼이 다섯 항목을 다
    # 받으므로 비는 경우가 없다. 일어나지 않는 일을 알리면 읽는 쪽이 비워도
    # 되는 줄로 읽는다.
    st.caption("ⓘ 여기서 넣은 값이 기획안 생성에 그대로 들어갑니다. "
               "스타일·도수·맛 특성이 AI 가 페어링을 고르는 근거입니다.")


# ───────────────────────── API 사용량 (㉞) ─────────────────────────
#
# 예시 화면: docs/ref/관리화면(api사용량포함)_예시_피그마.pdf
#
# [건별로 다 펼치지 않는다]
#   한 줄씩 다 보여 주면 정보가 많아 읽기 어렵다. 합계와 평균을 먼저 보이고
#   건별은 최근 10건만 접어 둔다.
#
# [평균은 유료 줄만으로 낸다]
#   무료는 금액이 0 이라 함께 평균을 내면 값이 희석된다.
#
# [기록 이전 사용분]
#   api_usage 가 쌓이기 전에 쓴 금액이 있다. 구글 결제 화면에서 확인한 값이고
#   (config/settings.GEMINI_SPENT_BEFORE_KRW), 총액에만 더한다. 종류별·날짜별
#   비중은 기록된 것만으로 낸다 — 그 전 사용분은 금액만 알고 종류를 모른다.


def _bar(pct: float) -> str:
    """막대 하나. 넘치면 100% 에서 멈춘다."""
    w = max(0.0, min(pct, 100.0))
    return (f'<div style="background:#EEF0F3; border-radius:999px; height:10px;'
            f' overflow:hidden; margin:10px 0 6px">'
            f'<div style="width:{w}%; height:100%; background:#2563EB;'
            f' border-radius:999px"></div></div>')


def _won(n) -> str:
    return f"{int(n or 0):,}원"


# 상자 사이 여백.
#
# **열 묶음(st.columns) 아래에는 Streamlit 이 스스로 16px 을 준다. 위에는 없다.**
# 브라우저로 좌표를 재서 확인했다 — 열 묶음이 989 에서 끝나는데 다음 요소가
# 1005 에서 시작했다. 그래서 위에만 이만큼 넣어 주면 위아래가 같아진다.
#
# 빈 요소는 16px 아래로 줄어들지 않아(4px 을 넣어도 16px 로 그려졌다) 이 값을
# 16 보다 작게 잡을 수 없다. 더 벌리려면 GAP 을 올리고 열 묶음 **아래에도**
# `_gap(GAP - 16)` 을 넣어야 한다.
GAP = 16


def _gap(px: int = GAP) -> None:
    """상자 사이 여백. Streamlit 기본 간격은 0 이라 직접 넣는다."""
    st.markdown(f'<div style="height:{px}px"></div>', unsafe_allow_html=True)


# 「일별 사용금액」과 「평균 단가」 상자의 세로 길이. 나란히 놓이는 두 상자라
# 길이가 다르면 눈에 띈다. 한 값으로 묶어 둔다.
CARD_H = 290

# 일별 그래프에 보일 날수. 다 보이면 막대가 가늘어지고, 지금은 하루 금액이
# 수십 원이라 옛 날짜까지 볼 이유가 적다.
DAYS = 5

# 그래프 높이. **가로축 날짜 글자까지 포함한 전체 높이다.**
#
# `use_container_width=True` 로 넘기면 Altair 가 autosize fit 으로 그린다 —
# 주는 높이 안에 축 글자까지 들어가고 그림 영역이 그만큼 줄어든다. 앞서 축
# 글자가 높이 밖에 더 붙는 줄 알고 작게 잡았다가 상자 아래가 남았다.
#
# 상자 안에서 쓸 수 있는 높이: CARD_H 290 - 테두리·여백 2×16 = 258.
# 거기서 제목 줄(약 26)과 요소 사이 간격(16)을 뺀 216 이 그래프 몫이다.
CHART_H = 210


def render_usage() -> None:
    """
    제미나이 API 사용량 (시안 docs/ref/관리화면(api사용량포함)_예시_피그마.pdf).

    시안은 「이번 달 / 안내 금액 3,000원」을 기준선으로 뒀는데, 그 3,000원은
    대표님께 미리 말씀드린 추정치일 뿐 정해 둔 예산이 아니다. 대신 **선불
    충전액**에 견준다 — 다 쓰면 실제로 기획안 생성이 멈추는 값이다.
    """
    rows = usage.fetch()
    if not rows:
        st.info("아직 기록된 사용량이 없습니다.")
        return
    s = usage.summarize(rows)
    총, 충전 = s["쓴_금액"], s["충전_금액"]
    남은 = max(충전 - 총, 0)
    pct = 총 / 충전 * 100 if 충전 else 0

    c_title, c_pill = st.columns([3, 1], vertical_alignment="center")
    c_title.markdown(
        '<div style="font-size:1.15rem; font-weight:800; color:#161A1F">'
        '제미나이 API 사용량</div>'
        '<div style="color:#59606D; font-size:0.85rem; margin-top:2px">'
        f'선불 충전액 대비 · {datetime.now(KST):%Y-%m-%d} 기준</div>',
        unsafe_allow_html=True)
    c_pill.markdown(
        f'<div style="text-align:right"><span style="border:1px solid #E5E7EB;'
        f' border-radius:999px; padding:6px 14px; font-size:0.82rem;'
        f' color:#59606D">{USAGE_LOG_FROM}부터 기록</span></div>',
        unsafe_allow_html=True)
    st.markdown(
        '<div style="color:#59606D; font-size:0.85rem; margin:14px 0 12px">'
        '기록을 시작하기 전의 사용 내역은 금액만 확인할 수 있어 전체 금액과'
        ' 월별 합계에만 포함했습니다.</div>',
        unsafe_allow_html=True)

    # ── 큰 카드 — 누적·오늘·기능별 비중 ──
    #
    # 기능별 비중 띠는 **유료로 쓴 기능이 둘 이상일 때만** 띄운다. 지금은
    # 기획안 생성만 유료라 「기획안 생성 100.0%」 한 줄이 되는데, 나눌 것이
    # 없는 비중은 자리만 차지한다. 메뉴 수집을 유료로 돌리면 다시 나타난다.
    비중 = [(k, v["금액"]) for k, v in s["종류별"].items() if v["금액"]]
    쓴것 = sum(w for _, w in 비중) or 1
    strip = ""
    if len(비중) > 1:
        strip = (
            '<div style="background:#F8FAFC; border-radius:10px;'
            ' padding:12px 16px; margin-top:18px; font-size:0.88rem">'
            '<span style="color:#161A1F; font-weight:800; margin-right:14px">'
            '기능별 비중</span>'
            + " <span style='color:#D7DBE0'>|</span> ".join(
                f'<span style="color:#59606D">{k}</span> '
                f'<b style="color:#161A1F">{_won(w)}</b> '
                f'<span style="color:#9CA3AF">{w / 쓴것 * 100:.1f}%</span>'
                for k, w in 비중)
            + '</div>')

    st.markdown(
        '<div style="position:relative; background:#FFFFFF;'
        ' border:1px solid #E5E7EB; border-radius:14px; padding:22px 26px">'
        # 세로 구분선. 위아래 두 칸만 가르는 선이 아니라 **상자 전체를 덮는다** —
        # 칸 안에 두면 안내문이 시작되는 자리에서 끊긴다.
        #
        # 가로 위치는 왼쪽 칸이 차지하는 비율(2.4 / 3.4 = 70.588%)에서 나온다.
        # 상자 안쪽 너비가 얼마든 맞게, 좌우 여백 26px 을 셈에 넣어 둔다:
        #   26 + 0.70588 × (너비 − 52) = 0.70588 × 너비 − 10.7
        '<div style="position:absolute; top:0; bottom:0;'
        ' left:calc(70.588% - 10.7px); width:1px; background:#EEF0F3"></div>'
        '<div style="display:flex; align-items:stretch">'
        '<div style="flex:2.4; padding-right:26px">'
        '<div style="display:flex; justify-content:space-between;'
        ' align-items:center">'
        '<div style="color:#161A1F; font-weight:800">누적 사용금액'
        '<span style="color:#9CA3AF; font-weight:600"> · 선불 충전액 대비</span>'
        '</div>'
        f'<span style="background:#EFF4FF; color:#2563EB; border-radius:999px;'
        f' padding:5px 13px; font-size:0.8rem; font-weight:700">'
        f'{"충전액 이내" if 총 <= 충전 else "충전액 초과"}</span></div>'
        f'<div style="margin-top:14px"><span style="font-size:2.1rem;'
        f' font-weight:800; color:#161A1F">{_won(총)}</span>'
        f'<span style="font-size:1.1rem; color:#9CA3AF"> / {_won(충전)}</span>'
        f'</div>{_bar(pct)}'
        '<div style="display:flex; justify-content:space-between;'
        ' font-size:0.85rem; margin-top:4px">'
        f'<span style="color:#59606D">충전액의 {pct:.1f}% 사용</span>'
        f'<b style="color:#161A1F">남은 금액 {_won(남은)}</b></div></div>'
        '<div style="flex:1; padding-left:26px">'
        '<div style="color:#161A1F; font-weight:800">오늘 사용한 금액</div>'
        f'<div style="font-size:2.1rem; font-weight:800; color:#161A1F;'
        f' margin-top:10px">{_won(s["오늘"])}</div>'
        f'<div style="color:#9CA3AF; font-size:0.82rem; margin-top:4px">'
        f'이번 달 {_won(s["이번달"])}</div>'
        '<div style="color:#59606D; font-size:0.82rem; margin-top:10px;'
        ' line-height:1.5">기록된 유료 호출의 합계입니다.</div>'
        '</div></div>' + strip +
        '<div style="margin-top:14px; color:#59606D; font-size:0.84rem">'
        '※ 구글 단가로 계산한 어림값입니다. 실제 청구액과 다를 수 있습니다.</div>'
        f'<div style="color:#9CA3AF; font-size:0.82rem; margin-top:2px">'
        f'Google 단가 · 환율 1달러 = {KRW_PER_USD:,.0f}원 적용 · 기능별·날짜별'
        f' 비중은 {USAGE_LOG_FROM} 이후 기록 기준</div></div>',
        unsafe_allow_html=True)

    _gap()
    c_day, c_avg = st.columns([2, 1])

    with c_day, st.container(border=True, height=CARD_H):
        st.markdown(
            '<div style="display:flex; justify-content:space-between;'
            # 제목과 그래프 사이. 상자 안에 남는 22px 을 위아래로 나눠 그래프가
            # 가운데 오게 한다 (안쪽 높이 258 - 제목 26 - 그래프 210 = 22).
            ' align-items:baseline; margin-bottom:11px">'
            '<span><span style="font-weight:800; color:#161A1F">일별 사용금액'
            '</span><span style="color:#9CA3AF; font-size:0.78rem;'
            ' margin-left:8px">무료로만 쓴 날은 0원으로 나옵니다</span></span>'
            f'<span style="color:#9CA3AF; font-size:0.82rem">최근'
            f' {DAYS}일 · 단위 원</span></div>',
            unsafe_allow_html=True)
        날짜 = s["날짜별"][:DAYS][::-1]      # 최근 것부터 와 있다. 왼쪽이 옛날이 되게 뒤집는다
        if 날짜:
            # st.bar_chart 를 쓰지 않는다. 날짜 글자가 세로로 서고(labelAngle),
            # 손을 올렸을 때 나오는 이름도 고칠 수 없다. 둘 다 Altair 로만 된다.
            #
            # 칸 이름을 「금액(원)」으로 두면 Altair 가 괄호를 집계 함수로 읽는다
            # (`금액(원)` → 「원 칸의 금액 집계」). 칸은 「금액」으로 두고 보일
            # 이름만 title 로 준다.
            표 = pd.DataFrame({"날짜": [f"{d:%m/%d}" for d, _ in 날짜],
                              "금액": [w for _, w in 날짜]})
            st.altair_chart(
                alt.Chart(표)
                .mark_bar(color="#2563EB", cornerRadiusTopLeft=3,
                          cornerRadiusTopRight=3)
                .encode(
                    x=alt.X("날짜:N", sort=None,
                            axis=alt.Axis(labelAngle=0, title=None,
                                          labelColor="#59606D", labelPadding=6)),
                    y=alt.Y("금액:Q", axis=alt.Axis(title=None, tickCount=4,
                                                  labelColor="#9CA3AF")),
                    tooltip=[alt.Tooltip("날짜:N", title="날짜"),
                             alt.Tooltip("금액:Q", title="금액(원)", format=",")])
                .properties(height=CHART_H),
                use_container_width=True)
        else:
            st.caption("아직 기록된 날이 없습니다.")

    # ── 평균 단가 ──
    #
    # 가로줄이 상자 세로 가운데에 오게 한다. 위아래 칸을 flex:1 둘로 나누면
    # 내용 길이와 무관하게 선이 가운데에 선다. 네 방향 여백은 같은 값(PAD)이고,
    # 내용은 각 칸 안에서 가운데 정렬이다.
    PAD = 18
    유료종류 = {k: v for k, v in s["종류별"].items() if v["평균"]}
    half = (f'flex:1; min-height:0; padding:{PAD}px; display:flex;'
            f' flex-direction:column; justify-content:center')
    if 유료종류:
        위 = ('<div style="display:flex; justify-content:space-between;'
              ' align-items:center">'
              '<span style="font-weight:800; color:#161A1F">평균 단가</span>'
              '<span style="color:#9CA3AF; font-size:0.82rem">근사값</span></div>'
              # 「1건」이 아니라 「클릭 1번」이다. 기록은 호출 한 번이 아니라
              # 한 번 돌린 것을 한 줄로 남기므로(기획안은 4단계가 한 줄),
              # 줄 수가 곧 버튼을 누른 횟수다.
              + "".join(
                  f'<div style="margin-top:10px; color:#161A1F">{k} 클릭 1번'
                  f' 평균 <b>{_won(v["평균"])}</b></div>'
                  for k, v in 유료종류.items()))
        아래 = (f'<div style="color:#59606D; font-size:0.86rem">남은'
                f' {_won(남은)}으로 예상하면</div>'
                + "".join(
                    f'<div style="color:#161A1F; font-weight:700;'
                    f' margin-top:4px">{k} 클릭만 약 {남은 // v["평균"]:,}번</div>'
                    for k, v in 유료종류.items())
                + '<div style="color:#9CA3AF; font-size:0.8rem; margin-top:8px">'
                  '한 종류만 쓸 때의 어림입니다.</div>')
    else:
        위 = ('<div style="font-weight:800; color:#161A1F">평균 단가</div>'
              '<div style="color:#9CA3AF; font-size:0.86rem; margin-top:10px">'
              '유료로 쓴 기록이 없어 평균을 낼 수 없습니다.</div>')
        아래 = ('<div style="color:#9CA3AF; font-size:0.86rem">기획안을 한 번'
                ' 만들면 여기에 1건 평균이 나옵니다.</div>')

    c_avg.markdown(
        f'<div style="height:{CARD_H}px; box-sizing:border-box;'
        f' border:1px solid rgba(49,51,63,0.2); border-radius:0.5rem;'
        f' display:flex; flex-direction:column">'
        f'<div style="{half}">{위}</div>'
        f'<div style="flex:0 0 1px; background:#EEF0F3"></div>'
        f'<div style="{half}">{아래}</div></div>',
        unsafe_allow_html=True)

    # ── 최근 기록 ──
    #
    # st.container(border=True) 로 두지 않는다. 표가 이미 HTML 한 덩어리라
    # 컨테이너가 하는 일이 테두리뿐인데, 그 테두리가 마지막 줄에 가려 아래쪽이
    # 잘려 보였다. 테두리까지 직접 그리면 끝이 어디인지 분명해진다.
    # 테두리 모양은 왼쪽 두 상자(Streamlit 기본)와 같은 값으로 맞췄다.
    #
    # 마지막 줄에는 밑줄을 넣지 않는다. 카드 테두리와 겹쳐 두 줄로 보인다.
    #
    # 여기에는 _gap() 을 넣지 않는다. 바로 위가 열 묶음이라 Streamlit 이 이미
    # 16px 을 주고 있다 (GAP 설명 참고).
    줄 = s["최근"]
    st.markdown(
        '<div style="box-sizing:border-box; border:1px solid rgba(49,51,63,0.2);'
        ' border-radius:0.5rem; padding:16px">'
        '<div style="display:flex; justify-content:space-between;'
        ' align-items:center; margin-bottom:10px">'
        f'<span style="font-weight:800; color:#161A1F">최근 기록 ·'
        f' 최대 {len(줄)}건</span>'
        f'<span style="color:#9CA3AF; font-size:0.82rem">전체'
        f' {len(rows)}건</span></div>'
        '<div style="display:flex; color:#9CA3AF; font-size:0.82rem;'
        ' border-bottom:1px solid #EEF0F3; padding-bottom:8px">'
        '<span style="flex:1.6">시각</span><span style="flex:1.2">종류</span>'
        '<span style="flex:1.6">협력사</span>'
        '<span style="flex:0.6; text-align:right">금액</span></div>'
        + "".join(
            '<div style="display:flex; align-items:center;'
            ' font-size:0.88rem; padding:10px 0'
            + ('' if i == len(줄) - 1 else '; border-bottom:1px solid #F3F4F6')
            + '">'
            f'<span style="flex:1.6; color:#59606D">'
            f'{r["때"]:%Y-%m-%d %H:%M}</span>'
            f'<span style="flex:1.2; color:#161A1F; font-weight:700">'
            f'{r["kind"]}</span>'
            f'<span style="flex:1.6; color:#59606D">'
            f'{r.get("partner_name") or "—"}</span>'
            f'<span style="flex:0.6; text-align:right; color:#161A1F;'
            f' font-weight:700">'
            f'{_won(r.get("krw")) if r.get("krw") else "무료"}</span></div>'
            for i, r in enumerate(줄))
        + '</div>', unsafe_allow_html=True)


with tab_beer:
    render_lineup()

with tab_usage:
    render_usage()
