"""
관리 — 개발팀 및 이관 대비

프롬프트를 코드에서 분리해 비개발자가 수정할 수 있게 한다. 
"""
import _path
import re
from datetime import datetime, timedelta, timezone

import streamlit as st

from app.auth import require_owner
from app.theme import apply_chrome
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
st.caption("판매 중인 맥주 라인업과 기획안 생성에 사용할 설정을 관리합니다.")

t1, t2, t3 = st.tabs(["맥주 라인업", "프롬프트", "제약조건"])

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
    missing = [label for label, ok in (("맥주 이름", name), ("ml당 가격", price),
                                       ("스타일", style), ("도수", abv is not None),
                                       ("맛 특성", flavor)) if not ok]
    if missing:
        st.error("비어 있는 항목: " + ", ".join(missing))
        return
    if name.lower() in names:
        st.error(f"'{name}'은(는) 이미 판매 중인 라인업에 있습니다.")
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
        h1, h2 = st.columns([3, 2])
        h1.markdown(f"#### 현재 맥주 라인업 &nbsp;<span style='font-size:0.8rem;"
                    f"background:#EEF0F3;padding:2px 8px;border-radius:6px'>{len(beers)}종</span>",
                    unsafe_allow_html=True)
        h2.caption("✕ 판매를 종료한 맥주는 오른쪽 ✕로 라인업에서 내리세요.")

        widths = [2.4, 1.1, 1.6, 0.8, 3.4, 0.6]
        head = st.columns(widths)
        for col, label in zip(head, ["맥주 이름", "ml당 가격", "스타일", "도수", "맛 특성", "내리기"]):
            col.caption(label)

        if not beers:
            st.caption("판매 중인 맥주가 없습니다. 아래에서 추가해 주세요.")
        for b in beers:
            st.divider()
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

        st.divider()
        if not st.session_state.get(SS_BEER_ADD):
            a1, a2 = st.columns([1, 5], vertical_alignment="center")
            if a1.button("＋ 맥주 추가", use_container_width=True):
                st.session_state[SS_BEER_ADD] = True
                st.rerun()
            a2.caption("월 1회 교체되는 맥주를 여기서 넣고 내립니다.")
        else:
            render_add_form({(b["name"] or "").strip().lower() for b in beers})

    st.caption("ⓘ 여기서 넣은 값이 기획안 생성에 그대로 들어갑니다. "
               "스타일·도수·맛 특성이 비면 페어링이 추측으로 채워집니다.")


with t1:
    render_lineup()

with t2:
    st.caption("prompts/*.yaml 을 화면에서 수정합니다.")
    st.selectbox("대상", ["p1_analyst", "p2_chef", "p3_marketer", "p4_consultant",
                          "common_rules"])
    st.info("파일 내용을 불러와 편집합니다.")
    st.caption("W5 이후 구현 예정")

with t3:
    st.caption("폐기 사유를 긍정형 제약으로 변환해 누적합니다. (설계 결정 D2)")
    st.info("constraints.yaml 항목을 표시합니다.")
    st.caption("T34에서 구현 예정")