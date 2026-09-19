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
from app.proposal import (build_proposal, build_proposal_docx, missing_fields,
                          proposal_no, won)
from chain.inputs import (BOTTLING_INGREDIENTS, BOTTLING_SNS, MARGIN_REF,
                          NO_REC_REASON, NO_TREND_MENU, PAST_CASES,
                          WEATHER_PREF, build_beer_list, build_constraints,
                          build_events, build_partner_blockers,
                          build_partner_resources, build_partner_sns)
from chain.runner import run
from context.builder import build as build_context
from db.client import get_client

st.set_page_config(page_title="기획안 생성", page_icon="📝", layout="wide")
require_owner()

KST = timezone(timedelta(hours=9))
SS_RESULT = "plan_result"      # 체인 출력
SS_META = "plan_meta"          # 협력사·날짜 등 생성 조건

# 접근마다 색을 둔다. 탭이 셋인데 내용이 비슷해 어느 안을 보고 있는지
# 놓치기 쉽다 (9/19 화면 확인). 배지·왼쪽 띠에 쓴다.
APPROACH_COLOR = {"단품": "#9DC3E6", "세트": "#F7C59F", "포장": "#B5D99C"}
# 탭 버튼의 (테두리, 글자, 바탕) 색. 파스텔 테두리에 같은 계열의 진한 글자,
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
            rec_reason=NO_REC_REASON,
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


# ══════════════════════════════════════════
# 결과 표시
# ══════════════════════════════════════════

def _bullets(items) -> None:
    for x in items or []:
        st.write(f"- {x}")


def render_price(item: dict, per_ml) -> None:
    """
    가격을 역할 상자에서 떼어 따로 보인다.

    판매가를 「협력사가 준비」 안에 두면 그 돈을 협력사가 받는 것처럼 읽힌다.
    실제로 협력사가 받는 것은 매입가이고, 판매가는 손님에게 받는 돈이다.

    맥주값은 「세트」 안에서만 값에 들어간다. 바틀링은 손님이 원하는 만큼
    따라 마시는 셀프탭이라, 단품에서는 맥주가 별개 거래다.

    마진은 맥주 원가를 몰라 직접 계산이 불가능하고, 이 협업 기획에 꼭
    필요한 숫자도 아니기 때문에 따로 산출하지 않는다.
    """
    beer_name = (item.get("페어링_맥주") or {}).get("메뉴명") or "페어링 맥주"
    beer_price = int(per_ml * 500) if per_ml else None

    listed = item.get("정가_합")
    price = item.get("판매가_제안")
    menu_price = item.get("협력사_정가")

    # (4)가 낸 제안 매입가가 있으면 그것을, 없으면 (2)의 협력사 희망값을 쓴다
    deal = item.get("매입") or {}
    cost = (won(deal.get("바틀링_제안_매입가"))
            or won(item.get("협력사희망_매입가")))

    st.markdown("##### 가격")

    # 내역을 쌓고 합계를 아래에 둔다 (docs/ref/figma_세트구성.png).
    # 항목이 흩어져 있으면 총액을 머릿속에서 더해야 한다.
    with st.container(border=True):
        rows = [(item.get("메뉴명") or "메뉴", menu_price)]
        if listed:                      # 세트일 때만 맥주가 값에 들어간다
            rows.append((f"{beer_name} 500ml", beer_price))
        for label, value in rows:
            c_l, c_r = st.columns([3, 1])
            c_l.write(label)
            c_r.markdown(f"<div style='text-align:right'>"
                         f"{value:,}원</div>" if value else
                         "<div style='text-align:right'>미정</div>",
                         unsafe_allow_html=True)

        st.divider()

        if listed:
            c1, c2, c3 = st.columns(3)
            c1.metric("따로 사면", f"{listed:,}원")
            c2.metric("세트로 내는 값", f"{price:,}원" if price else "미정")
            if price and listed > price:
                c2.caption(f"{listed - price:,}원 싸다 · 맥주 500ml 이상")
        else:
            c2, c3 = st.columns(2)
            c2.metric("손님이 내는 값", f"{price:,}원" if price else "미정")
            c2.caption(f"맥주는 따로 계산 · {beer_name} 추천")

        c3.metric("협력사에 주는 값", f"{cost:,}원" if cost else "산출 불가")
        c3.caption("협의 대상" if cost else "협력사 납품가 미확보")


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

    text = build_proposal(item, meta)

    with st.container(border=True):
        st.markdown("##### 협업 제안서")
        st.caption(f"{proposal_no(meta)} · 협력사에 그대로 보낼 수 있는 문서입니다.")

        deal = item.get("매입") or {}
        if deal.get("협의_필요"):
            st.info("제안 매입가는 협의 대상입니다. 협력사의 원가를 알 수 없으므로 "
                    "이 값은 협상의 출발점으로 쓰십시오.")

        st.code(text, language=None)

        c1, c2 = st.columns(2)
        try:
            # 탭마다 버튼이 하나씩이라 key 가 없으면 Streamlit 이 같은 버튼으로 본다
            c1.download_button(
                "Word로 내려받기",
                data=build_proposal_docx(text, meta),
                file_name=f"{proposal_no(meta)}_{item.get('접근') or item.get('안_id')}_협업제안서.docx",
                mime=("application/vnd.openxmlformats-officedocument"
                      ".wordprocessingml.document"),
                use_container_width=True,
                key=f"docx_{item.get('안_id')}",
            )
        except Exception as e:
            c1.caption(f"Word 생성 실패 — 위 본문을 복사해 쓰십시오 ({e})")
        c2.caption("본문 오른쪽 위 아이콘으로 전체 복사할 수 있습니다.")


def render_plan(item: dict, meta: dict) -> None:
    """
    안 하나. 대표님이 이 화면만 보고 실행 여부를 정할 수 있어야 한다.

    [읽는 순서] 명세서 4-2 — 이 문서만 보고 실행 여부를 정할 수 있어야 한다
      ① 무엇을 파는가   ② 왜 이 안인가   ③ 얼마가 남는가
      ④ 누가 무엇을 하는가   ⑤ 어떻게 알리는가   ⑥ 무엇이 걸리는가

    돈 이야기를 역할 상자에서 떼어 ③으로 모은다. 판매가가 「협력사가 준비」
    안에 있으면 그 돈을 협력사가 받는 것처럼 읽힌다.
    """
    # ── ① 무엇을 파는가 ──
    #
    # 이미지가 없으면 그 자리를 두지 않는다. 미구현 자리표시자가 티켓 번호와
    # 함께 대표님 화면에 남아 있으면 안 된다.
    # 접근을 색 배지로, 메뉴명과 떼어 보인다. 접근 이름이 메뉴명에 섞이면
    # "단품 소보로빵" 처럼 읽혀 어느 쪽이 이름인지 헷갈린다.
    approach = item.get("접근") or item.get("안_id") or ""
    color = APPROACH_COLOR.get(approach, "#9CA3AF")
    head = (
        f'<div style="border-left:6px solid {color}; padding:4px 14px; margin:4px 0 10px 0;">'
        f'<span style="background:{color}; color:#fff; padding:2px 12px; border-radius:12px; '
        f'font-size:0.85rem; font-weight:600; vertical-align:middle;">{approach}</span>'
        f'<span style="font-size:1.5rem; font-weight:700; margin-left:12px; vertical-align:middle;">'
        f'{item.get("메뉴명") or "이름 없음"}</span></div>'
    )
    img = item.get("메뉴_이미지")
    if img:
        c_txt, c_img = st.columns([2, 1])
        with c_txt:
            st.markdown(head, unsafe_allow_html=True)
            st.write(item.get("구성") or "")
        c_img.image(img, use_container_width=True)
    else:
        st.markdown(head, unsafe_allow_html=True)
        st.write(item.get("구성") or "")

    # ── ② 왜 이 안인가 ──
    if item.get("선정_사유"):
        with st.container(border=True):
            st.markdown("##### 선정 사유")
            st.write(item["선정_사유"])

    # ── ③ 얼마가 남는가 ──
    beer = item.get("페어링_맥주") or {}
    per_ml = beer.get("원_ml")
    render_price(item, per_ml)

    # ── ④ 누가 무엇을 하는가 ──
    #
    # 품목과 조건만 남긴다. 금액은 ③ 이 다룬다.
    st.markdown("##### 구성과 역할")
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.markdown("**협력사가 준비**")
            _bullets(item.get("협력사_제공"))
            st.write("")
            st.caption(f"보관　{item.get('보관_조건') or '데이터 없음'}")
            st.caption(f"납품　{item.get('1회_납품_수량') or '1회 수량 협의'}")
    with c2:
        with st.container(border=True):
            st.markdown("**바틀링이 준비**")
            st.write(f"- {beer.get('메뉴명') or '페어링 맥주 없음'} 500ml")
            _bullets(item.get("바틀링_준비"))
            if beer.get("이유"):
                st.write("")
                st.caption(f"페어링 이유　{beer['이유']}")

    # ── ⑤ 어떻게 알리는가 ──
    ev = item.get("이벤트") or {}
    with st.container(border=True):
        st.markdown(f"##### 홍보 — {ev.get('명칭') or '이벤트 없음'}")
        st.write(ev.get("내용") or "")
        st.caption(f"기간 {ev.get('기간') or '미정'}")

        schedule = item.get("홍보_일정") or []
        if schedule:
            # st.dataframe 은 행이 둘뿐이어도 스크롤 영역을 만든다.
            # st.table 은 내용만큼 늘어나므로 짧은 표에 맞다.
            st.table(schedule)

        copy = item.get("홍보_문구")
        if copy:
            # st.code 는 우측 상단에 복사 버튼이 붙는다.
            #
            # 문구의 말투까지 프롬프트로 규정하지 않는다. 어떤 문구가 먹히는지는
            # SNS 를 다뤄 본 사람이 안다. 초안임을 밝히고 다듬어 쓰게 둔다.
            # 루브릭 「홍보 실효성」 채점(5-2)에서 같은 지적이 반복되면
            # 그때 constraints 로 올린다 (명세서 1-5).
            st.code(copy, language=None)
            st.caption("초안입니다. 다듬어 쓰세요.")
        tags = item.get("해시태그") or []
        if tags:
            st.caption(" ".join(tags))

    # ── ⑥ 무엇이 걸리는가 ──
    #
    # 준비물은 펼쳐 두고, 길이가 크게 튀는 둘만 접는다.
    with st.container(border=True):
        st.markdown("##### 실행 준비물")
        _bullets(item.get("실행_준비물"))

    risks = item.get("예상_리스크") or []
    if risks:
        with st.expander(f"예상 리스크 {len(risks)}건"):
            _bullets(risks)

    basis = item.get("추천_근거") or {}
    if basis:
        with st.expander("추천 근거"):
            for k, v in basis.items():
                st.markdown(f"**{k.replace('_', ' ')}** — {v}")

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

    # 고르는 자리와 결과를 확실히 끊는다
    st.divider()

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
            # 색은 안쪽 배지와 왼쪽 띠(render_plan)가 낸다.
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

# 고를 것이 몇 개 안 되므로 폭을 다 쓰지 않는다. 제목부터 버튼까지 가운데 열에
# 두고 양옆을 비운다. 열 안에서는 왼쪽 정렬 그대로다.
_, c_in, _ = st.columns([1.5, 2, 1.5])
with c_in:
    st.markdown("<h1 style='text-align:center; margin-bottom:2rem'>기획안 생성</h1>",
                unsafe_allow_html=True)
    pid = st.selectbox("협력사", list(labels), format_func=labels.get)

    chosen = next(p for p in partners if p["id"] == pid)

    rnd = round_of(chosen)
    st.caption(f"{rnd}차 기획안 — "
               + ("협력사 입력 전입니다. 후기에서 확인한 메뉴·판매가로 만듭니다."
                  if rnd == 1 else "협력사가 폼으로 알려준 값으로 만듭니다."))

    has_menus = bool(chosen.get("menu_prices"))
    if not has_menus:
        st.info("메뉴·판매가가 아직 없습니다. 들어오면 만들 수 있습니다.")

    # 협의 가능한 때를 여기서 보인다. 매입가와 납품 수량은 결국 통화로
    # 정해야 하는데, 그 값이 DB 에만 있으면 찾아볼 생각을 못 한다.
    if chosen.get("contact_slots"):
        st.caption(f"협의 가능 — {chosen['contact_slots']}")

    # 납품 가능 요일도 함께 보인다.
    #
    # 실행일이 그 요일과 어긋나면 당일 만든 것을 받아야 하는 메뉴는 팔 수가
    # 없다. 체인은 이것을 고칠 수 없다 — 실행일은 여기서 사람이 고르는
    # 값이라 메뉴를 몇 번 다시 만들어도 같은 문제가 남는다.
    if chosen.get("available_slots"):
        st.caption(f"납품 가능 — {chosen['available_slots']}")

    # 명세서 4-2 는 「날짜 지정 / 희망 기간」 두 방식을 둔다.
    # 희망 기간은 (1)을 요일 수만큼 반복 호출해야 해 T45(W4)로 미뤘다.
    mode = st.radio("실행일", ["날짜 지정", "희망 기간"], horizontal=True)
    is_range = mode == "희망 기간"
    target = st.date_input(
        "실행 희망일", label_visibility="collapsed",
        value=datetime.now(KST).date() + timedelta(days=7),
        disabled=is_range)

    if is_range:
        st.caption("희망 기간 방식은 아직 준비 중입니다. 날짜를 지정해 주세요.")

    st.write("")
    go = st.button("기획안 생성", type="primary",
                   use_container_width=True,
                   disabled=is_range or not has_menus)

st.divider()

if go:
    generate(chosen, target)

if st.session_state.get(SS_RESULT):
    render_result(st.session_state[SS_RESULT], st.session_state[SS_META])
elif not go:
    st.info("협력사와 실행일을 고르고 생성을 누르면 약 20초 뒤 기획안 3안이 나옵니다.")
