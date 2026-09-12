"""
협력사 자원 입력 — 초대 코드로 접근하는 공개 페이지 (T21, 명세서 4-1)

[중요] 이 페이지만 대표님 로그인 없이 열린다.
       URL: .../협력사_입력?code=A7K2
       코드가 유효하지 않으면 어떤 정보도 노출하지 않는다.

작성 소요 3분 이내가 목표다. 선택지를 미리 채워 타이핑을 줄인다.

[무엇을 묻고 무엇을 안 묻나]
  협업이 완제품 매입 하나로 정해지면서(기획서 6-1) 묻는 것이 바뀌었다.

  묻는다   지금 팔고 있는 메뉴와 가격 — 사 올 물건이 곧 이것이다.
           실제 판매가를 알아야 매입가 제안에 근거가 생긴다.
  안 묻는다 보유 식재료·장비 — 완성품을 사 오므로 무엇으로 어떻게
           만드는지는 우리 일이 아니다.
  안 묻는다 협업 가능 형태 — 매입 하나뿐이라 고를 것이 없다.
"""
import _path  # noqa: F401  (프로젝트 루트를 sys.path 에 추가)
import streamlit as st

from app.auth import is_owner, verify_invite
from context.builder import INDUSTRY_MAP
from db.client import get_client

st.set_page_config(page_title="협력사 정보 입력", page_icon="📋")

# 업종은 매출 데이터와 이어져 있다. INDUSTRY_MAP 에 없는 업종을 고르면
# 상권 분석에 그 업종 매출을 실을 수 없다 (명세서 3-2).
CATEGORIES = list(INDUSTRY_MAP)

MENU_ROWS = 5        # 폼에 미리 깔아 두는 줄 수
MENU_MIN = 3         # 이 아래로는 저장하지 않는다


def _int(v) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def rows_to_menus(rows) -> list[dict]:
    """표 입력에서 빈 줄을 걷어내고 값을 정수로 맞춘다."""
    out = []
    for r in rows or []:
        name = str(r.get("메뉴") or "").strip()
        if not name:
            continue
        out.append({"메뉴": name,
                    "가격": _int(r.get("가격")),
                    "납품가": _int(r.get("납품가"))})
    return out


def save(partner_id: int, values: dict) -> bool:
    try:
        (get_client().table("partners")
         .update(values).eq("id", partner_id).execute())
        return True
    except Exception as e:
        st.error(f"저장에 실패했습니다 — {e}")
        return False


code = st.query_params.get("code", "")
partner = verify_invite(code)

if not partner and not is_owner():
    st.title("협력사 정보 입력")
    st.warning("유효한 링크로 접속해 주세요.")
    st.caption("바틀링에서 전달받으신 주소를 확인해 주십시오.")
    st.stop()

# 대표님이 로그인 상태로 들어오면 내용을 볼 수 있게 하되 저장은 막는다.
# 실제 협력사 데이터를 대신 고쳐 버리면 누가 쓴 값인지 알 수 없어진다.
preview = partner is None
if preview:
    partner = {}

st.title("협력사 정보 입력")
st.caption(f"{partner.get('name') or '(미리보기)'} · 약 3분이면 끝납니다.")

if preview:
    st.info("미리보기입니다. 이 화면에서는 저장되지 않습니다.")

st.markdown("**지금 팔고 계신 메뉴와 가격**, **제약 사항**을 자세히 "
            "적어주실수록 실행 가능한 기획이 나옵니다.")

with st.form("partner"):
    name = st.text_input("가게 이름", value=partner.get("name") or "")

    cat = partner.get("category")
    category = st.selectbox(
        "업종", CATEGORIES,
        index=CATEGORIES.index(cat) if cat in CATEGORIES else 0)

    st.markdown("##### 지금 팔고 계신 메뉴와 가격")
    st.caption(f"{MENU_MIN}개 이상 적어주세요. 지금 팔고 계신 것 그대로면 "
               "됩니다.")

    saved = partner.get("menu_prices") or []
    blank = {"메뉴": "", "가격": None, "납품가": None}
    rows = list(saved) + [dict(blank)
                          for _ in range(max(0, MENU_ROWS - len(saved)))]
    menus = st.data_editor(
        rows, num_rows="dynamic", use_container_width=True,
        column_config={
            "메뉴": st.column_config.TextColumn("메뉴", required=False),
            "가격": st.column_config.NumberColumn("파시는 가격(원)",
                                                min_value=0, step=100,
                                                format="%d"),
            "납품가": st.column_config.NumberColumn("바틀링에 주실 값(원)",
                                                 min_value=0, step=100,
                                                 format="%d"),
        },
        key="menus")
    st.caption("납품가는 비워두셔도 됩니다. 그 메뉴는 협의해서 정합니다.")

    signature = st.text_input(
        "그중 대표 메뉴", value=partner.get("signature_menu") or "",
        placeholder="가장 많이 나가는 것 하나")

    slots = st.text_input(
        "납품 가능한 요일과 시간",
        value=partner.get("available_slots") or "",
        placeholder="예: 화~일 오전 중 가능. 월요일 휴무")
    contact = st.text_input(
        "협의 가능한 시간",
        value=partner.get("contact_slots") or "",
        placeholder="예: 평일 오전 / 브레이크타임 15~17시",
        help="전화나 방문으로 이야기 나누기 편하신 때")

    st.markdown("##### SNS")
    st.caption("바틀링과 함께 올리면 같은 노력으로 두 배가 닿습니다. "
               "적어주시면 홍보 기획에 반영됩니다.")
    # 「안 합니다」와 빈칸을 구분한다. 빈칸은 아직 안 적은 것이고,
    # 「안 합니다」는 확인된 사실이다. (3)이 다르게 판단한다.
    channels = ["", "인스타그램", "블로그", "틱톡", "유튜브", "페이스북",
                "카카오톡 채널", "안 합니다"]
    ch = partner.get("sns_channel")
    c1, c2 = st.columns(2)
    sns = c1.selectbox(
        "주로 쓰시는 SNS", channels,
        index=channels.index(ch) if ch in channels else 0,
        help="여러 곳을 하시면 가장 자주 올리시는 한 곳만 골라주세요. "
             "협업 때 그 채널에 한 번 올려주시는 것을 부탁드립니다.")
    kinds = ["", "릴스", "피드", "스토리", "숏츠", "영상", "글"]
    kind = partner.get("sns_content_type")
    content = st.selectbox("주로 올리시는 것", kinds,
                           index=kinds.index(kind) if kind in kinds else 0)

    st.markdown("##### 제약 사항")
    blockers = st.text_area(
        "지켜야 할 조건", height=120, label_visibility="collapsed",
        value="\n".join(partner.get("blockers") or []),
        placeholder="한 번에 50개까지만 만들 수 있습니다\n"
                    "당일 만든 것만 드릴 수 있습니다\n"
                    "저희 상호를 표기해 주셔야 합니다")
    st.caption("한 줄에 하나씩 적어주세요. 적어주신 조건을 모두 지켜서 "
               "기획을 만듭니다. 특별히 없으시면 「없음」이라고 "
               "적어주세요.")

    submitted = st.form_submit_button("제출", use_container_width=True,
                                      disabled=preview)

if not submitted:
    st.stop()

menu_rows = rows_to_menus(menus)
blocker_rows = [x.strip() for x in blockers.splitlines() if x.strip()]

# 비어 있는 채로 저장되면 (2)가 무엇을 사 올지 모른다.
# 무엇이 모자란지 한 번에 알려준다 — 하나씩 알리면 왕복이 는다.
missing = []
if not name.strip():
    missing.append("가게 이름")
if len(menu_rows) < MENU_MIN:
    missing.append(f"팔고 계신 메뉴 {MENU_MIN}개 이상")
elif any(m["가격"] is None for m in menu_rows):
    missing.append("적으신 메뉴의 가격")
if not slots.strip():
    missing.append("납품 가능한 요일과 시간")
if not contact.strip():
    missing.append("협의 가능한 시간")
if not blocker_rows:
    missing.append("제약 사항")

if missing:
    st.error("다음을 적어주세요 — " + " · ".join(missing))
    st.stop()

values = {
    "name": name.strip(),
    "category": category,
    "menu_prices": menu_rows,
    "signature_menu": signature.strip() or menu_rows[0]["메뉴"],
    "available_slots": slots.strip(),
    "contact_slots": contact.strip(),
    "sns_channel": sns or None,
    "sns_content_type": content or None,
    "blockers": blocker_rows,
}

if save(partner["id"], values):
    st.success("제출되었습니다. 감사합니다.")
    st.caption(f"같은 주소로 다시 들어오시면 수정하실 수 있습니다 "
               f"(확인 코드 {code}).")
