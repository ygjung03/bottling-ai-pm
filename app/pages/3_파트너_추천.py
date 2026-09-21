"""
파트너 추천 — 세 경로 병행 (T24, 명세서 4-3 · W3-W4계획 5-6)

경로 구성 (5-6)
  A. 추천받기   — T15 점수(nearby_stores.score) 기준. 필터 → 표 → 지도 → 상세
  B. 직접 지정  — 상호 검색(반경 1km 안이면 참고 점수도 같이 보여줌, 순위엔 안 씀) / 목록에 없으면 직접 입력
  C. 메뉴로 찾기 — U17(블로그 검색) 계정이 아직 없어 지도 링크만 제공하는 대체 경로로 구현 (3-5 "U17 실패 시" 방침)

공통 — 후보를 고르면 partners 등록 여부를 확인해 등록됐으면 기획안 생성으로,
안 됐으면 초대 코드 발급. (scripts/new_partner.py와 같은 방식).

"""
import secrets
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import pydeck as pdk
import streamlit as st

from app.auth import require_owner
from app.theme import apply_chrome
from context.builder import INDUSTRY_MAP
from db.client import get_client
from recommender.complement import TIER_LABELS, guess_industry_category, tier_label
from recommender.scoring import score_store

st.set_page_config(page_title="파트너 추천", page_icon="🔍", layout="wide",
                   initial_sidebar_state="collapsed")
require_owner()
apply_chrome()

client = get_client()

BOTTLING_COORD = (37.5318919, 127.0679483)  
RADIUS_M = 1000

# [9/21] 대표님 「협업 업종 적합도 조사」로 업종 구분이 6개 → 12개로 증가
# (recommender/complement.py TIER_LABELS 참조). 색도 그만큼 늘려 구별.
TIER_COLOR = {
    "제과·디저트": "#F59E0B",
    "피자·치킨": "#EF4444",
    "수제버거": "#B91C1C",
    "분식": "#22C55E",
    "토스트·샌드위치·샐러드": "#84CC16",
    "카페": "#2F6FED",
    "아이스크림·빙수": "#38BDF8",
    "한식": "#9CA3AF",
    "중식": "#FB923C",
    "일식": "#F472B6",
    "양식": "#A78BFA",
    "주점": "#6B21A8",
}


def hex_to_rgb_list(hex_color, alpha=255):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return [r, g, b, alpha]


# ───────────────────────── 데이터 조회 ─────────────────────────

@st.cache_data(ttl=300)
def load_scored_candidates() -> pd.DataFrame:
    """점수가 매겨진 후보(T15 완료분)만 가져온다. score IS NOT NULL."""
    res = (
        client.table("nearby_stores")
        .select("store_id,name,category_l,category_m,category_s,address,"
                "lat,lng,distance_m,score,score_detail")
        .not_.is_("score", "null")
        .order("score", desc=True)
        .limit(5000)  
        .execute()
    )
    df = pd.DataFrame(res.data)
    if df.empty:
        return df
    df["tier"] = df.apply(lambda r: tier_label(r.get("category_m"), r.get("category_s")), axis=1)
    return df


@st.cache_data(ttl=300)
def count_total_candidates() -> int:
    res = client.table("nearby_stores").select("store_id", count="exact").execute()
    return res.count or 0


@st.cache_data(ttl=300)
def load_partner_names() -> set[str]:
    """이미 등록된 협력사 이름 집합 — 추천 표에 '등록' 여부를 바로 표시하는 용도.
    find_existing_partner()의 ilike(와일드카드 없음) 매칭과 같은 기준(대소문자 무시·
    앞뒤 공백 제거)으로 통일."""
    res = client.table("partners").select("name").execute()
    return {(r.get("name") or "").strip().lower() for r in res.data}


def search_nearby(query: str, limit: int = 20) -> list[dict]:
    try:
        return (
            client.table("nearby_stores")
            .select("store_id,name,category_m,category_s,address,lat,lng,"
                    "distance_m,score,score_detail")
            .ilike("name", f"%{query.strip()}%")
            .limit(limit)
            .execute()
            .data
        )
    except Exception as e:
        st.error(f"검색 실패 — {e}")
        return []


def find_existing_partner(name: str) -> dict | None:
    if not name or not name.strip():
        return None
    try:
        rows = (
            client.table("partners")
            .select("id,name,invite_code,category")
            .ilike("name", name.strip())
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None
    except Exception:
        return None


def create_invite(name: str, category: str, lat=None, lng=None) -> dict | None:
    """새 협력사 행을 만들고 초대 코드 발급 (scripts/new_partner.py와 동일 방식).
    같은 상호가 이미 있으면 새로 만들지 않고 기존 코드 반환"""
    existing = find_existing_partner(name)
    if existing:
        return existing

    payload = {"name": name.strip(), "category": category, "invite_code": secrets.token_urlsafe(12)}
    if lat is not None:
        payload["lat"] = lat
    if lng is not None:
        payload["lng"] = lng

    try:
        rows = client.table("partners").insert(payload).execute().data
        load_partner_names.clear() 
        return rows[0] if rows else None
    except Exception as e:
        st.error(f"등록 실패 — {e}")
        return None


# ───────────────────────── 공통 UI 조각 ─────────────────────────

def render_next_step(candidate_name: str, guessed_category: str, lat=None, lng=None, key_prefix=""):
    """추천받기·직접 지정 공통 — 이후 처리 (명세서 4-3 공통 절차)."""
    existing = find_existing_partner(candidate_name)
    if existing:
        st.warning(f"'{existing['name']}'은(는) 이미 등록된 협력사입니다.")
        st.page_link("pages/2_기획안_생성.py", label="기획안 생성으로 이동", icon="📝")
        return

    st.info(f"'{candidate_name}'은(는) 아직 등록되지 않았습니다.")
    if st.button("협력사 등록", key=f"{key_prefix}_invite_btn"):
        row = create_invite(candidate_name, guessed_category, lat, lng)
        if row:
            render_registered(row, guessed_category)


def render_registered(row: dict, guessed_category: str):
    """등록 직후 안내. 버튼 경로와 직접 입력 폼 경로가 같이 쓴다."""
    st.success("협력사를 등록했습니다. 기획안 생성에서 고를 수 있습니다.")
    st.code(row.get("invite_code") or "", language=None)
    st.caption(
        f"위 코드는 협력사가 관심을 보인 뒤 구글 폼을 보낼 때 확인 코드로 쓰입니다. "
        f"업종은 '{guessed_category}'(으)로 초안을 채웠습니다 — "
        f"협력사가 폼에서 직접 고칠 수 있습니다."
    )
    st.page_link("pages/2_기획안_생성.py", label="기획안 생성으로 이동", icon="📝")


def render_map(df: pd.DataFrame, highlight_store_id: str | None = None, top_n: int = 60):
    if df.empty:
        st.info("지도에 표시할 후보가 없습니다.")
        return

    shown = df.head(top_n)
    features = [{
        "name": "바틀링", "lat": BOTTLING_COORD[0], "lon": BOTTLING_COORD[1],
        "color": [31, 41, 51, 230], "radius": 45, "label": "바틀링 (기준점)",
    }]
    for _, r in shown.iterrows():
        if pd.isna(r.get("lat")) or pd.isna(r.get("lng")):
            continue
        is_hl = highlight_store_id is not None and r["store_id"] == highlight_store_id
        color_hex = TIER_COLOR.get(r["tier"], "#9CA3AF")
        features.append({
            "name": r["name"], "lat": r["lat"], "lon": r["lng"],
            "color": hex_to_rgb_list(color_hex, 255 if is_hl else 175),
            "radius": 42 if is_hl else 26,
            "label": f"{r['name']} · {r['tier']} · {int(r['distance_m'])}m · 점수 {r['score']:.2f}",
        })

    map_df = pd.DataFrame(features)
    point_layer = pdk.Layer(
        "ScatterplotLayer", data=map_df,
        get_position="[lon, lat]", get_fill_color="color", get_radius="radius",
        radius_min_pixels=5, radius_max_pixels=32,
        stroked=True, get_line_color=[255, 255, 255, 220], line_width_min_pixels=1.5,
        pickable=True,
    )
    radius_ring = pdk.Layer(
        "ScatterplotLayer",
        data=[{"lat": BOTTLING_COORD[0], "lon": BOTTLING_COORD[1]}],
        get_position="[lon, lat]", get_radius=RADIUS_M,
        filled=False, stroked=True,
        get_line_color=[47, 111, 237, 140], line_width_min_pixels=1.5,
    )

    lats = [f["lat"] for f in features]
    lons = [f["lon"] for f in features]
    view = pdk.ViewState(
        latitude=sum(lats) / len(lats), longitude=sum(lons) / len(lons), zoom=14, pitch=0,
    )
    st.pydeck_chart(
        pdk.Deck(layers=[radius_ring, point_layer], initial_view_state=view,
                 tooltip={"text": "{label}"}, map_style=None),
        height=420, use_container_width=True,
    )
    legend = " · ".join(f'<span style="color:{c}">●</span> {name}' for name, c in TIER_COLOR.items())
    st.markdown(f'<div style="font-size:0.8rem;color:#6B7280;">{legend}</div>', unsafe_allow_html=True)


# ───────────────────────── 화면 ─────────────────────────

st.title("파트너 추천")
st.caption("명세서 4-3 — 추천받기 · 직접 지정 · 메뉴로 찾기, 세 경로를 병행합니다.")

tab_rec, tab_manual, tab_menu = st.tabs(["추천받기", "직접 지정", "메뉴로 찾기"])

# ── A. 추천받기 ──
with tab_rec:
    candidates = load_scored_candidates()

    if candidates.empty:
        st.warning("추천 점수가 없습니다. `python -m recommender.run` 을 먼저 실행해 주세요 (T15).")
    else:
        total = count_total_candidates()
        partner_names = load_partner_names()
        candidates = candidates.copy()
        candidates["등록됨"] = candidates["name"].apply(
            lambda n: (n or "").strip().lower() in partner_names
        )

        c1, c2 = st.columns([1, 3])
        with c1:
            radius = st.slider("반경 (m)", 200, 1000, 1000, step=100, key="rec_radius")
            tiers = st.multiselect(
                "업종", TIER_LABELS,
                default=TIER_LABELS, key="rec_tiers",
            )
            hide_registered = st.checkbox(
                "이미 등록된 협력사 숨기기", value=True, key="rec_hide_registered",
                help="partners 테이블에 같은 이름이 이미 있으면 후보에서 뺍니다.",
            )

        filtered = candidates[
            (candidates["distance_m"] <= radius) & (candidates["tier"].isin(tiers))
        ]
        if hide_registered:
            filtered = filtered[~filtered["등록됨"]]
        filtered = filtered.reset_index(drop=True)
        filtered.insert(0, "순위", range(1, len(filtered) + 1))

        unmapped = total - len(candidates)
        hidden_by_filter = len(candidates) - len(filtered)
        registered_total = int(candidates["등록됨"].sum())

        with c2:
            extra = (
                f" (그중 이미 등록된 {registered_total}곳)" if hide_registered and registered_total
                else f" · 이미 등록된 협력사 {registered_total}곳 포함" if registered_total
                else ""
            )
            st.caption(
                f"추천 후보 {len(filtered)}곳 · "
                f"프랜차이즈 추정·업종 미매핑으로 제외한 {unmapped}곳(3-1·3-2 원칙) · "
                f"현재 필터로 {hidden_by_filter}곳 더 숨김{extra}"
            )
            # 고르는 칸을 표 맨 오른쪽 열에 체크박스로 둔다. st.dataframe 의 행 선택은
            # 표 왼쪽 끝에 숨은 체크 칸을 눌러야 해서 눈에 안 띄었다 — 셀을 눌러도
            # 아무 일이 없어 등록이 안 되는 줄 알았다 (9/21). 등록 여부 열은 뺐다.
            # 이미 등록된 곳을 고르면 아래에서 경고로 알린다. 다른 열은 편집 잠금.
            view = filtered[["순위", "name", "tier", "distance_m", "score"]].rename(
                columns={"name": "상호", "tier": "업종", "distance_m": "거리(m)", "score": "점수"}
            )
            view["선택"] = False
            edited = st.data_editor(
                view, use_container_width=True, hide_index=True, key="rec_table",
                disabled=[c for c in view.columns if c != "선택"],
                column_config={"선택": st.column_config.CheckboxColumn(
                    "선택", help="체크하면 아래에 상세와 등록 버튼이 나옵니다")},
            )

        picked = edited.index[edited["선택"]].tolist()
        selected_idx = picked[0] if picked else None
        if len(picked) > 1:
            st.caption("한 곳씩 봅니다. 위에서부터 첫 번째로 체크한 곳을 보여줍니다.")

        st.divider()
        if selected_idx is None:
            st.caption("표에서 후보를 선택하면 상세 정보가 여기에 표시됩니다.")
        else:
            row = filtered.iloc[selected_idx]
            detail_col, map_col = st.columns([1, 1])

            with detail_col:
                st.markdown(f"#### {row['name']}")
                st.caption(f"{row['tier']} · 도보 약 {round(row['distance_m'] / 67)}분 ({int(row['distance_m'])}m)")

                result = score_store(row.to_dict())
                if result:
                    st.write(result["reason"])
                    st.markdown(f"[네이버 지도에서 확인]({result['naver_map_url']})")

                sd = row["score_detail"] or {}
                st.markdown("**점수 구성**")
                st.progress(float(sd.get("S_distance", 0)), text=f"거리 {sd.get('S_distance', 0):.2f}")
                st.progress(float(sd.get("S_complement", 0)), text=f"업종 상보성 {sd.get('S_complement', 0):.2f}")
                st.caption(f"종합 {row['score']:.3f} = 0.5×거리 + 0.5×업종 상보성 (명세서 3-2)")

                st.divider()
                render_next_step(
                    row["name"],
                    guess_industry_category(row.get("category_m"), row.get("category_s")),
                    row.get("lat"), row.get("lng"),
                    key_prefix="rec",
                )

            with map_col:
                render_map(filtered, highlight_store_id=row["store_id"])

# ── B. 직접 지정 ──
with tab_manual:
    st.caption("이미 협업할 가게를 정해두신 경우 여기서 바로 지정합니다.")
    query = st.text_input("가게 이름 검색", key="manual_query")

    selected = None
    if query:
        found = search_nearby(query)
        if found:
            st.write(f"{len(found)}건 검색됨")
            for r in found:
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.markdown(f"**{r['name']}**")
                        cat = r.get("category_s") or r.get("category_m") or "업종 미상"
                        dist = r.get("distance_m")
                        st.caption(cat + (f" · {int(dist)}m" if dist is not None else " · 반경 1km 밖"))
                        if r.get("score") is not None:
                            st.caption(f"참고 점수 {r['score']:.2f} — 직접 지정이라 순위엔 쓰지 않습니다 (4-3)")
                        else:
                            st.caption("참고 점수 없음 (업종 미분류 또는 매핑 대상 아님)")
                    with c2:
                        if st.button("이 가게로 진행", key=f"manual_pick_{r['store_id']}"):
                            st.session_state["manual_selected"] = r

            sel = st.session_state.get("manual_selected")
            if sel and sel.get("store_id") in [r["store_id"] for r in found]:
                selected = sel
        else:
            st.info("검색 결과가 없습니다. 반경 밖이거나 목록에 없는 가게일 수 있습니다 — 아래에 직접 입력해 주세요.")

    if selected:
        st.divider()
        render_next_step(
            selected["name"],
            guess_industry_category(selected.get("category_m"), selected.get("category_s")),
            selected.get("lat"), selected.get("lng"),
            key_prefix="manual",
        )

    with st.expander("검색 결과에 없으면 직접 입력", expanded=bool(query) and not selected):
        with st.form("manual_entry"):
            m_name = st.text_input("가게 이름")
            m_category = st.selectbox("업종", list(INDUSTRY_MAP))
            submitted = st.form_submit_button("협력사 등록")
            # partners 테이블에 주소 컬럼이 없어(lat/lng만 있음) 여기선 안 받는다.
            # 위치가 필요하면 등록 후 대표님이 직접 좌표를 채운다.

        # 폼 제출 결과 안에 버튼을 또 두지 않는다. 그 버튼을 누르면 화면이
        # 다시 실행되는데 그때는 submitted 가 False 라 이 블록이 통째로
        # 사라지고, 등록은 되지 않는다(9/18 화면 확인). 제출 시 바로 등록한다.
        if submitted:
            if not m_name.strip():
                st.error("가게 이름을 입력해 주세요.")
            else:
                st.divider()
                existing = find_existing_partner(m_name)
                if existing:
                    st.warning(f"'{existing['name']}'은(는) 이미 등록된 협력사입니다.")
                    st.page_link("pages/2_기획안_생성.py", label="기획안 생성으로 이동", icon="📝")
                else:
                    row = create_invite(m_name, m_category)
                    if row:
                        render_registered(row, m_category)

# ── C. 메뉴로 찾기 ──
with tab_menu:
    st.caption("메뉴 이름을 넣으면 관련 업종의 가까운 가게를 찾습니다 (2차 방문 요구사항, 명세서 3-5).")
    st.info(
        "메뉴로 실제로 걸러주는 기능(T48)은 네이버 검색 API(지역검색) 키 승인 대기 중입니다 — "
        "승인되면 '메뉴 검색 → 반경 필터 → nearby_stores 대조'로 교체될 예정입니다(9/28 이후). "
        "지금은 업종 필터로만 후보를 추리고, 링크는 검색 결과가 뜨도록 네이버 통합검색으로 엽니다 "
        "(지도 검색 링크는 빈 화면이 뜨는 문제가 있어 바꿨습니다)."
    )

    menu_name = st.text_input("메뉴 이름", placeholder="예: 두바이 초콜릿", key="menu_name")
    menu_tiers = st.multiselect(
        "관련 업종 (메뉴 성격에 맞게 골라주세요)",
        TIER_LABELS, default=TIER_LABELS,
        key="menu_tiers",
    )

    if menu_name:
        candidates = load_scored_candidates()
        matched = candidates[candidates["tier"].isin(menu_tiers)].sort_values("distance_m")
        st.write(f"'{menu_name}' 관련 업종 후보 {len(matched)}곳 (거리순)")
        for _, r in matched.head(20).iterrows():
            store_name = r["name"]
            search_q = f"{store_name} {menu_name}"
            url = f"https://search.naver.com/search.naver?query={quote(search_q)}"
            st.markdown(f"- **{store_name}** ({r['tier']}, {int(r['distance_m'])}m) — [네이버에서 검색]({url})")
        if matched.empty:
            st.caption("조건에 맞는 후보가 없습니다. 업종 선택을 넓혀보세요.")