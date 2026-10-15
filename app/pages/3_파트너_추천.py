"""
파트너 추천 — 세 경로 병행 (T24, 명세서 4-3 · W3-W4계획 5-6)

경로 구성 (5-6)
  A. 추천받기   — T15 점수(nearby_stores.score) 기준. 필터 → 표 → 지도 → 상세
  B. 직접 지정  — 상호 검색(반경 1km 안이면 참고 점수도 같이 보여줌, 순위엔 안 씀) / 목록에 없으면 직접 입력
  C. 메뉴로 찾기 — U17(블로그 검색) 계정이 아직 없어 지도 링크만 제공하는 대체 경로로 구현 (3-5 "U17 실패 시" 방침)

공통 — 후보를 고르면 partners 등록 여부를 확인해 등록됐으면 기획안 생성으로,
안 됐으면 초대 코드 발급. (scripts/new_partner.py와 같은 방식).

"""
import re
import secrets
import sys
from datetime import date, datetime, timedelta, timezone

# 배포는 UTC 라 그냥 today() 를 쓰면 새벽에 캘린더 기본값이 어제로 뜬다.
KST = timezone(timedelta(hours=9))
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import pydeck as pdk
import streamlit as st

from app.auth import require_owner
from app.theme import SS_PARTNER_ID, SS_PARTNER_TAB, apply_chrome, just_arrived
from context.builder import INDUSTRY_MAP
from db.client import get_client
from recommender.complement import TIER_LABELS, guess_industry_category, tier_label
from recommender.scoring import score_store
from recommender import agent as rec_agent
from recommender import menu_search

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


# ── 사장님 말로 보이기 (10/14) ──
# 화면에 「점수 0.81」「업종 상보성」 같은 개발 용어가 그대로 나왔다. 실제로 쓰는 사람은
# 바틀링 대표님이라, 점수는 100점 만점으로, 용어는 풀어서 보인다.

def fit_score(score) -> int | None:
    """0~1 점수를 100점 만점 정수로. 0.61 과 0.69 를 가를 수 있게 점 모양 대신 숫자로 보인다."""
    try:
        return round(float(score) * 100)
    except (TypeError, ValueError):
        return None


def fit_label(score) -> str:
    n = fit_score(score)
    return f"궁합 {n}점" if n is not None else "궁합 정보 없음"


# 행사가 어디서 왔는지 (events.source → 화면에 보일 이름)
EVENT_SOURCE = {"seoul_api": "서울시 문화행사", "gwangjin_board": "광진구청 소식",
                "naver_news": "네이버 뉴스"}
STORE_SOURCE = "소상공인시장진흥공단 상가정보"


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
        st.error("가게를 찾지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
        st.caption(f"오류 내용: {e}")
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


def create_invite(name: str, category: str, lat=None, lng=None,
                  address: str | None = None) -> dict | None:
    """새 협력사 행을 만들고 초대 코드 발급 (scripts/new_partner.py와 동일 방식).
    같은 상호가 이미 있으면 새로 만들지 않고 기존 코드 반환

    주소는 블로그 후기에서 메뉴를 모을 때 검색어에 「광진구」를 붙이는 데 쓴다.
    이름만으로 찾으면 전국의 같은 이름 가게가 섞인다 (db/migrate_1005.sql).
    """
    existing = find_existing_partner(name)
    if existing:
        return existing

    payload = {"name": name.strip(), "category": category, "invite_code": secrets.token_urlsafe(12)}
    if lat is not None:
        payload["lat"] = lat
    if lng is not None:
        payload["lng"] = lng
    if address:
        payload["address"] = address

    try:
        rows = client.table("partners").insert(payload).execute().data
        load_partner_names.clear() 
        return rows[0] if rows else None
    except Exception as e:
        st.error("등록하지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
        st.caption(f"오류 내용: {e}")
        return None


# ───────────────────────── 공통 UI 조각 ─────────────────────────

def hand_over(partner: dict) -> None:
    """고른 협력사를 기획안 생성 화면에 넘긴다.

    기획안 생성 화면이 이 값을 협력사 고르는 칸의 기본값으로 읽는다. 안 넣으면
    파트너추천에서 협력사로 고르고나서 기획안 생성 화면에서 또 골라야 한다.

    넘어가는 순간이 아니라 협력사가 정해지는 자리에서 넣는다 — 링크는 코드를
    돌릴 수 없고, 세션 값은 화면을 옮겨도 남는다.

    셀렉트박스 key("partner_pick")에 직접 넣으면 안 된다. Streamlit 이 위젯을
    안 그린 실행에서 그 값을 지우므로, 화면을 넘어가는 사이에 사라진다.
    """
    pid = partner.get("id")
    if pid:
        st.session_state[SS_PARTNER_ID] = pid


def go_to_plan(store: dict) -> None:
    """고른 가게로 기획안 생성 화면을 연다. 등록이 안 돼 있으면 등록까지 한다.

    「이 가게로 간다」고 누른 자리에서 부른다. 누른 사람은 이미 그 가게로
    정했는데, 전에는 등록 안내를 한 번 더 보여 주고 버튼을 또 누르게 했다.
    묻는 값도 없었다 — 업종은 상가정보에서 추정하고, 협력사가 폼에서 고친다.

    **누른 그 자리에서만 부른다.** render_next_step 안에 두면 안 된다 — 거기는
    추천 표에서 행을 고르기만 해도 그려지는 자리라, 상세를 보려고 고른 것뿐인데
    화면이 넘어가고 가게가 등록돼 버린다.

    등록에 실패하면 화면을 넘기지 않고 그대로 둔다. create_invite 가 오류를
    띄우므로 누른 사람이 무슨 일이 났는지 본다.
    """
    name = (store.get("name") or "").strip()
    if not name:
        return
    row = find_existing_partner(name) or create_invite(
        name,
        guess_industry_category(store.get("category_m"), store.get("category_s")),
        store.get("lat"), store.get("lng"), store.get("address"),
    )
    if not row:
        return
    hand_over(row)
    # 가게를 정하고 넘어가므로 추천 결과는 소임을 다했다. 두고 가면 나중에
    # 다시 들어왔을 때 지난 카드가 선택된 채로 보인다.
    for k in ("rec_ai_result", "rec_plan", "rec_ai_chosen", "rec_pick_id",
              "manual_selected", "menu_search_result", "menu_pick",
              "menu_pick_store"):
        st.session_state.pop(k, None)
    st.switch_page("pages/2_기획안_생성.py")


def render_next_step(candidate_name: str, guessed_category: str, lat=None, lng=None,
                     key_prefix="", address: str | None = None):
    """추천받기·직접 지정 공통 — 이후 처리 (명세서 4-3 공통 절차)."""
    existing = find_existing_partner(candidate_name)
    if existing:
        st.warning(f"'{existing['name']}'은(는) 이미 등록된 협력사입니다.")
        hand_over(existing)
        st.page_link("pages/2_기획안_생성.py", label="기획안 생성으로 이동", icon="📝")
        return

    st.info(f"'{candidate_name}'은(는) 아직 등록되지 않았습니다.")
    if st.button("협력사 등록", key=f"{key_prefix}_invite_btn"):
        row = create_invite(candidate_name, guessed_category, lat, lng, address)
        if row:
            render_registered(row, guessed_category)


def render_registered(row: dict, guessed_category: str):
    """
    등록 직후 처리. 버튼 경로와 직접 입력 폼 경로가 같이 쓴다.

    확인 코드는 보여주지 않는다 (9/30). 등록할 때 만들어 두지만 사람이 읽고
    옮겨 적을 값이 아니다 — 협의 자리에서 쓸 때는 보관함이 그 코드가 박힌
    폼 링크를 통째로 내준다.

    업종(`guessed_category`)은 초안으로 채워 두고 협력사가 폼에서 고친다.
    여기서 따로 알리지 않는다 — 넘어간 화면에 그대로 보인다.
    """
    hand_over(row)
    # 등록은 「이 가게와 한다」고 정한 뒤에만 누르는 버튼이라, 끝나면 바로
    # 기획안 생성으로 보낸다. 전에는 안내와 링크만 띄워 한 번 더 눌러야 했다.
    # 업종 초안은 그 화면에서 그대로 보이고 폼에서 협력사가 고칠 수 있다.
    st.switch_page("pages/2_기획안_생성.py")


@st.dialog("알림")
def warn_one_pick():
    """추천 표에서 둘 이상 체크했을 때 화면 가운데 띄우는 알림."""
    st.markdown(
        '<div style="line-height:1.8; margin:6px 0 14px">'
        '한 곳만 선택할 수 있습니다.<br>다른 곳을 선택하려면 현재 선택을 먼저 해제해 주세요.</div>',
        unsafe_allow_html=True)
    if st.button("확인", type="primary", use_container_width=True):
        st.rerun()


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
            "label": f"{r['name']} · {r['tier']} · {int(r['distance_m'])}m · {fit_label(r['score'])}",
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


POOL_COLS = ["store_id", "name", "tier", "distance_m", "score",
             "category_m", "category_s", "address", "lat", "lng"]


# ───────────────────────── 추천받기 — AI 에이전트 ─────────────────────────

SS_REC_AI = "rec_ai_result"
# 고른 날짜·행사·메뉴 아이디어를 기획안 생성 화면으로 넘기는 자리.
# {"date": "YYYY-MM-DD", "event": str | None, "menu": str,
#  "store_id": str, "name": str}
#
# 기획안 생성 화면은 date 를 희망일 첫 값으로, menu 를 메뉴 방향 참고로 읽는다
# (rec_menu_hint). name 은 그 화면에서 고른 협력사와 같은 가게인지 보는 데 쓴다 —
# 추천을 받고 나서 목록에서 다른 협력사로 바꿀 수 있다. 이름을 맞춰 둔 자리라
# 바꾸면 조용히 빠진다.
SS_REC_PLAN = "rec_plan"
WEEKDAY = "월화수목금토일"
REC_MAX_DAYS = 60       # 뉴스 행사를 60일까지 모은다 (ingest/events.py NEWS_LOOKAHEAD_DAYS)


def _fmt_day(d: date) -> str:
    return f"{d.month}/{d.day}({WEEKDAY[d.weekday()]})"


def render_ai_recommend(candidates: pd.DataFrame) -> None:
    """
    기간을 받아 AI 가 날짜·가게·메뉴 아이디어를 1~5위로 제안한다 (recommender/agent.py).

    카드에서 「이 안으로 진행」을 누르면 아래 점수 표의 같은 가게가 선택된 상태가 되어,
    기존 상세 → 협력사 등록 → 기획안 생성 흐름을 그대로 탄다.
    """
    st.markdown("#### AI 추천 — 언제 · 누구와 · 무엇을")
    st.caption("협업 가능 기간을 선택하면, 해당 기간의 인근 행사와 궁합이 높은 "
               "매장을 바탕으로 AI가 날짜·매장·협업 메뉴 아이디어를 제안합니다.")

    today = datetime.now(KST).date()
    picked = st.date_input(
        "협업 가능 기간", value=rec_agent.default_range(today),
        min_value=today, max_value=today + timedelta(days=REC_MAX_DAYS),
        format="YYYY-MM-DD", key="rec_ai_range",
        help=f"행사는 오늘부터 {REC_MAX_DAYS}일 안의 것만 모아 둡니다.",
    )
    ready = isinstance(picked, (tuple, list)) and len(picked) == 2
    if not ready:
        st.caption("시작일과 종료일을 모두 선택해 주십시오.")

    if st.button("AI 추천받기", type="primary", disabled=not ready, key="rec_ai_btn"):
        start, end = picked
        free = candidates[~candidates["등록됨"]]
        picks, events = None, []
        # 30초 가까이 걸려 단계를 보여 준다 (기획안 생성 화면의 진행 표시와 같은 생각)
        with st.status("추천을 만드는 중…", expanded=True) as box:
            try:
                pool = free[POOL_COLS].head(rec_agent.MAX_CANDIDATES).to_dict("records")
                st.write(f"① 궁합 상위 매장 {len(pool)}곳 선정")

                def on_step(name, n):
                    if name == "events":
                        st.write(f"② 기간 안의 근처 행사 확인 — {n}건")
                    elif name == "ai":
                        st.write("③ AI가 날짜·매장·메뉴를 선정하는 중… (10~30초)")

                def on_wait(sec, _attempt):
                    st.write(f"　요청이 많아 {sec}초 후 다시 시도합니다…")

                from chain.inputs import build_beer_list
                picks, events = rec_agent.recommend(start, end, pool, build_beer_list(),
                                                    on_wait=on_wait, on_step=on_step)
                box.update(label=f"추천 {len(picks)}건을 만들었습니다", state="complete",
                           expanded=False)
            except Exception as e:
                box.update(label="추천을 만들지 못했습니다", state="error", expanded=True)
                st.error("추천을 만들지 못했습니다. 잠시 뒤 다시 눌러 주세요.")
                st.caption(f"오류 내용: {e}")
        if picks is not None:
            st.session_state[SS_REC_AI] = {"range": (start, end), "picks": picks,
                                           "events": events,
                                           "at": datetime.now(KST).strftime("%m/%d %H:%M")}
            st.session_state.pop("rec_ai_chosen", None)

    result = st.session_state.get(SS_REC_AI)
    if not result:
        return

    start, end = result["range"]
    picks = result["picks"]
    if not picks:
        st.warning("유효한 추천 결과가 없습니다. 기간을 변경하거나 다시 시도해 주십시오.")
        return

    st.caption(f"{_fmt_day(start)} ~ {_fmt_day(end)} 기준 · 메뉴는 업종으로 낸 아이디어입니다 "
               f"(가게의 실제 메뉴는 협력사 등록 뒤에 모읍니다).")
    # 어디서 온 정보인지 — 대표님이 믿을 근거 (10/14)
    st.caption(f"정보 출처 · 가게: {STORE_SOURCE} · 행사: "
               + ", ".join(EVENT_SOURCE.values())
               + (f" · 추천 시각 {result['at']}" if result.get("at") else ""))

    # 고른 안이 있으면 그 카드만 펼치고, 나머지는 「다른 추천 보기」로 접는다.
    chosen_id = st.session_state.get("rec_ai_chosen")
    chosen = [p for p in picks if p["store"]["store_id"] == chosen_id]
    others = [p for p in picks if p["store"]["store_id"] != chosen_id]
    if chosen:
        _ai_card(chosen[0], result["events"], chosen=True)
        with st.expander(f"다른 추천 보기 ({len(others)})"):
            for p in others:
                _ai_card(p, result["events"], nested=True)
    else:
        for p in picks:
            _ai_card(p, result["events"])

    if result["events"]:
        with st.expander(f"AI가 본 행사 {len(result['events'])}건"):
            for e in result["events"]:
                src = EVENT_SOURCE.get(e.get("source"), "")
                st.caption(f"{e['start_date']} ~ {e.get('end_date')} · {e.get('title')}"
                           + (f" · {src}" if src else ""))


def _event_note(name: str | None, events: list[dict]) -> str:
    """연계 행사 옆에 붙일 「기간 · 출처」. 이름이 행사 목록과 안 맞으면 빈 문자열."""
    if not name:
        return ""
    key = re.sub(r"\s", "", name)
    for e in events:
        title = re.sub(r"\s", "", e.get("title") or "")
        if title and (title in key or key in title):
            span = (e["start_date"][5:].replace("-", "/") if e["start_date"] == e.get("end_date")
                    else f"{e['start_date'][5:].replace('-', '/')}~{(e.get('end_date') or '')[5:].replace('-', '/')}")
            src = EVENT_SOURCE.get(e.get("source"), "")
            return f" ({span}{' · ' + src if src else ''})"
    return ""


def _ai_card(p: dict, events: list[dict], chosen: bool = False, nested: bool = False) -> None:
    """
    추천 카드 한 장 — 두 줄로 짧게. 이유 3줄은 접어 둔다 (10/14).

    고른 카드에는 다음 단계(협력사 등록 / 기획안 생성으로 이동)를 바로 아래에 그린다.
    전에는 아래 점수 표에서만 선택이 바뀌어, 눌러도 아무 반응이 없어 보였다.
    """
    store = p["store"]
    with st.container(border=True):
        head, btn = st.columns([5, 1.4], vertical_alignment="center")
        mark = "✓ " if chosen else ""
        head.markdown(f"**{mark}{p['rank']}위 · {_fmt_day(p['date'])} · {store['name']}**")
        head.caption(f"{store.get('tier') or '업종 미상'} · 도보 약 "
                     f"{round(store['distance_m'] / 67)}분 ({int(store['distance_m'])}m) · "
                     f"{fit_label(store['score'])}")
        if not chosen and btn.button("이 안으로 진행", key=f"rec_ai_go_{p['rank']}",
                                     use_container_width=True):
            st.session_state[SS_REC_PLAN] = {
                "date": p["date"].isoformat(), "event": p["event"],
                "menu": p["menu"], "store_id": store["store_id"],
                "name": store["name"],
            }
            # 아래 점수 표에서도 같은 가게가 체크된 상태로 다시 그린다
            st.session_state["rec_pick_id"] = store["store_id"]
            st.session_state["rec_table_ver"] = st.session_state.get("rec_table_ver", 0) + 1
            st.session_state["rec_ai_chosen"] = store["store_id"]
            # 여기서 화면이 기획안 생성으로 바뀐다. 아직 등록 안 된 가게면
            # 등록하고 넘어간다.
            go_to_plan(store)
            st.rerun()

        st.markdown(f"<span style='color:#59606D'>연계 행사</span> {p['event'] or '없음'}"
                    f"<span style='color:#9CA3AF; font-size:0.85em'>{_event_note(p['event'], events)}</span>"
                    f" &nbsp;·&nbsp; <span style='color:#59606D'>메뉴 아이디어</span> "
                    f"{p['menu'] or '-'}", unsafe_allow_html=True)
        # 접힌 목록(「다른 추천 보기」) 안에서는 접기를 겹칠 수 없어 작은 글씨로 보인다
        if nested:
            for i, r in enumerate(p["reasons"], 1):
                st.caption(f"{i}. {r}")
        else:
            with st.expander("추천 이유 보기", expanded=chosen):
                for i, r in enumerate(p["reasons"], 1):
                    st.markdown(f"{i}. {r}")

        if chosen:
            st.success("이 안을 선택했습니다. 날짜와 메뉴 방향이 기획안 생성 화면으로 전달됩니다.")
            render_next_step(
                store["name"],
                guess_industry_category(store.get("category_m"), store.get("category_s")),
                store.get("lat"), store.get("lng"),
                key_prefix=f"rec_ai_{p['rank']}", address=store.get("address"),
            )


# ───────────────────────── 화면 ─────────────────────────

st.title("파트너 추천")
st.caption("협업 매장을 찾는 세 가지 방법 — AI 추천, 직접 지정, 메뉴로 찾기")

# 탭 — st.tabs 대신 라디오를 탭처럼 그린다 (10/14).
# st.tabs 는 코드로 탭을 고를 수 없어, 홈의 「정해 둔 매장이 있어요」「메뉴로 찾기」가
# 눌러도 늘 첫 탭이 열렸다. 라디오는 세션 값으로 고를 수 있고, 고른 칸만 실행되어
# 다른 탭의 무거운 계산(AI 추천 후보 등)도 돌지 않는다.
TAB_NAMES = ["추천받기", "직접 지정", "메뉴로 찾기"]
TAB_KEY = "partner_tab_ctl"

_want = st.session_state.pop(SS_PARTNER_TAB, None)     # 홈에서 넘어올 때만 들어 있다
if _want in TAB_NAMES:
    st.session_state[TAB_KEY] = _want

st.markdown("""<style>
.st-key-partner_tabs div[role="radiogroup"] {
    gap: 0 !important; border-bottom: 1px solid #E7E7EA; width: 100%; margin-bottom: 0.6rem;
}
.st-key-partner_tabs div[role="radiogroup"] > label {
    margin: 0 !important; padding: 0.55rem 1rem 0.65rem; cursor: pointer;
    border-bottom: 2px solid transparent; margin-bottom: -1px !important;
}
.st-key-partner_tabs div[role="radiogroup"] > label > div:first-child { display: none; }  /* 동그라미 숨김 */
.st-key-partner_tabs div[role="radiogroup"] > label p { font-size: 0.95rem; color: #6B7280; }
.st-key-partner_tabs div[role="radiogroup"] > label:hover p { color: #0F1115; }
.st-key-partner_tabs div[role="radiogroup"] > label:has(input:checked) { border-bottom-color: #0F1115; }
.st-key-partner_tabs div[role="radiogroup"] > label:has(input:checked) p { color: #0F1115; font-weight: 700; }
</style>""", unsafe_allow_html=True)
with st.container(key="partner_tabs"):
    _tab = st.radio("보기", TAB_NAMES, horizontal=True, key=TAB_KEY,
                    label_visibility="collapsed")

# 이 화면에 들어오거나 탭을 옮기면 세 탭의 지난 결과를 모두 지운다.
#
# 결과는 전부 세션 값이라 탭을 옮기거나 화면을 나갔다 와도 남는다. 그래서 다시
# 들어오면 지난 추천 카드와 「이 안을 선택했습니다」가 그대로 떠 있어, 새로
# 찾으러 온 것인데 전에 고른 가게가 선택된 채로 보였다.
#
# 탭만 봐서는 모자란다 — 기획안 생성으로 넘어갔다가 상단 바로 돌아오면 탭은
# 그대로라 안 지워진다. 그래서 화면에 막 들어온 실행인지를 함께 본다.
#
# 키 이름을 글자 그대로 적는다 — SS_MENU_PICK·SS_MENU_RESULT 는 이 줄보다
# 아래에서 정해져서 여기서는 아직 이름으로 부를 수 없다.
# 위젯 key(`manual_query`·`menu_name`·`rec_ai_range`)는 건드리지 않는다. 지운
# 것은 결과를 담아 둔 값들뿐이고, 입력칸에 쳐 둔 글자는 그대로 남는다.
_STALE = ("rec_ai_result", "rec_plan", "rec_ai_chosen", "rec_pick_id",
          "manual_selected", "menu_search_result", "menu_pick", "menu_pick_store")
if just_arrived() or st.session_state.get("partner_tab_seen") != _tab:
    st.session_state["partner_tab_seen"] = _tab
    for _k in _STALE:
        st.session_state.pop(_k, None)

# ── A. 추천받기 ──
if _tab == "추천받기":
    candidates = load_scored_candidates()

    if candidates.empty:
        st.warning("추천할 가게 목록이 아직 준비되지 않았습니다. 개발팀에 알려 주세요.")
    else:
        total = count_total_candidates()
        partner_names = load_partner_names()
        candidates = candidates.copy()
        candidates["등록됨"] = candidates["name"].apply(
            lambda n: (n or "").strip().lower() in partner_names
        )

        render_ai_recommend(candidates)
        st.divider()
        # 점수표·상세·지도는 접어 둔다 (10/14). AI 추천이 이 탭의 첫 화면이고, 표를
        # 펼쳐 두면 화면이 너무 길어진다. 표에서 직접 고르는 길은 그대로 남는다.
        with st.expander("점수 순 전체 후보 보기", expanded=False):

            c1, c2 = st.columns([1, 3])
            with c1:
                radius = st.slider("반경 (m)", 200, 1000, 1000, step=100, key="rec_radius")
                tiers = st.multiselect(
                    "업종", TIER_LABELS,
                    default=TIER_LABELS, key="rec_tiers",
                )
                hide_registered = st.checkbox(
                    "이미 등록된 협력사 숨기기", value=True, key="rec_hide_registered",
                    help="이미 협력사로 등록된 매장은 목록에서 제외합니다.",
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
                    f"프랜차이즈 및 협업이 어려운 업종 {unmapped}곳은 사전에 제외했습니다 · "
                    f"현재 조건으로 {hidden_by_filter}곳 미표시{extra} · 매장 정보: {STORE_SOURCE}"
                )
                # 고르는 칸을 표 맨 오른쪽 열에 체크박스로 둔다. st.dataframe 의 행 선택은
                # 표 왼쪽 끝에 숨은 체크 칸을 눌러야 해서 눈에 안 띄었다 — 셀을 눌러도
                # 아무 일이 없어 등록이 안 되는 줄 알았다 (9/21). 등록 여부 열은 뺐다.
                # 이미 등록된 곳을 고르면 아래에서 경고로 알린다. 다른 열은 편집 잠금.
                #
                # 한 곳만 고른다. 표 안의 체크박스라 두 번째 클릭 자체는 못 막으므로,
                # 둘 이상 체크되면 먼저 고른 것만 남기고 표를 다시 그린 뒤 팝업으로
                # 알린다 (9/22). 고른 곳은 행 번호가 아니라 store_id 로 기억한다 —
                # 반경·업종 필터를 바꾸면 행 번호가 밀린다. 표를 다시 그리려면 key 를
                # 바꿔야 해서 버전 번호를 key 에 붙인다.
                if st.session_state.pop("rec_pick_warn", False):
                    warn_one_pick()
                pick_id = st.session_state.get("rec_pick_id")
                ver = st.session_state.get("rec_table_ver", 0)
                view = filtered[["순위", "name", "tier", "distance_m", "score"]].rename(
                    columns={"name": "상호", "tier": "업종", "distance_m": "거리(m)", "score": "궁합"}
                )
                view["궁합"] = (view["궁합"].astype(float) * 100).round().astype(int)
                view["선택"] = (filtered["store_id"] == pick_id).tolist()
                edited = st.data_editor(
                    view, use_container_width=True, hide_index=True, key=f"rec_table_{ver}",
                    disabled=[c for c in view.columns if c != "선택"],
                    column_config={"선택": st.column_config.CheckboxColumn(
                        "선택", help="체크하면 아래에 상세와 등록 버튼이 나옵니다"),
                        "궁합": st.column_config.ProgressColumn(
                            "궁합", min_value=0, max_value=100, format="%d점",
                            help="거리가 가깝고 바틀링과 업종이 겹치지 않을수록 높습니다 (100점 만점)")},
                )

            picked_ids = filtered.loc[edited["선택"].tolist(), "store_id"].tolist()
            if len(picked_ids) > 1:
                keep = pick_id if pick_id in picked_ids else picked_ids[0]
                st.session_state["rec_pick_id"] = keep
                st.session_state["rec_table_ver"] = ver + 1
                st.session_state["rec_pick_warn"] = True
                st.rerun()
            st.session_state["rec_pick_id"] = picked_ids[0] if picked_ids else None
            selected_idx = filtered.index[filtered["store_id"] == picked_ids[0]][0] if picked_ids else None

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
                    st.markdown(f"**추천 근거** · {fit_label(row['score'])}")
                    st.progress(float(sd.get("S_distance", 0)), text="바틀링과 가까움")
                    st.progress(float(sd.get("S_complement", 0)),
                                text="바틀링과 겹치지 않는 업종 (대표님 업종 조사 기준)")
                    st.caption("두 항목을 같은 비중으로 합산하여 궁합 점수(100점 만점)를 산출합니다.")

                    st.divider()
                    render_next_step(
                        row["name"],
                        guess_industry_category(row.get("category_m"), row.get("category_s")),
                        row.get("lat"), row.get("lng"),
                        address=row.get("address"),
                        key_prefix="rec",
                    )

                with map_col:
                    render_map(filtered, highlight_store_id=row["store_id"])

# ── B. 직접 지정 ──
if _tab == "직접 지정":
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
                            st.caption(f"{fit_label(r['score'])} (참고용)")
                        else:
                            st.caption("궁합 정보 없음 (업종을 확인할 수 없는 매장)")
                    with c2:
                        if st.button("이 가게로 진행", key=f"manual_pick_{r['store_id']}"):
                            st.session_state["manual_selected"] = r
                            go_to_plan(r)   # 필요하면 등록하고 바로 넘어간다

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
            address=selected.get("address"),
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
                st.error("매장 이름을 입력해 주십시오.")
            else:
                st.divider()
                existing = find_existing_partner(m_name)
                if existing:
                    st.warning(f"'{existing['name']}'은(는) 이미 등록된 협력사입니다.")
                    hand_over(existing)
                    st.page_link("pages/2_기획안_생성.py", label="기획안 생성으로 이동", icon="📝")
                else:
                    row = create_invite(m_name, m_category)
                    if row:
                        render_registered(row, m_category)

# ── C. 메뉴로 찾기 ──
#
# 메뉴 이름 → 관련 업종 점수 상위 30곳 → 가게마다 블로그 「가게명 + 메뉴」 →
# 언급이 있는 곳 중 점수 순 상위 5곳 (recommender/menu_search.py).
#
# 고른 메뉴는 기획안 생성으로 넘긴다. 담기는 것:
#   {"menu": str, "store_id": str, "name": str}
# 기획안 생성 화면이 menu 를 trend_menu 자리에 읽는다 (B 와 맞춘 이름 — 바꾸면
# 조용히 빠진다). name 은 그 화면에서 고른 협력사와 같은 가게인지 보는 데 쓴다.
SS_MENU_PICK = "menu_pick"
SS_MENU_RESULT = "menu_search_result"


@st.cache_data(ttl=3600, show_spinner=False)
def run_menu_search(menu: str, rows: tuple) -> dict:
    """같은 메뉴·같은 후보면 한 시간 동안 다시 검색하지 않는다 (가게마다 1회 호출)."""
    res = menu_search.search(menu, [dict(r) for r in rows])
    return dict(res, at=datetime.now(KST).strftime("%m/%d %H:%M"))


def _menu_card(i: int, r: dict, menu: str) -> None:
    with st.container(border=True):
        st.markdown(f"**{i}위 · {r['name']}**")
        st.caption(f"{r.get('tier') or '업종 미상'} · 도보 약 {round(r['distance_m'] / 67)}분 "
                   f"({int(r['distance_m'])}m) · {fit_label(r['score'])}")
        links = f"[네이버 지도](https://map.naver.com/p/search/{quote(r['name'])})"
        if r.get("sample_url"):
            links += f" · [관련 후기 예시]({r['sample_url']})"
        st.markdown(f"네이버 블로그 후기 **{r['mentions']}건**에서 확인 · {links}")
        if st.button("이 가게로 진행", key=f"menu_go_{r['store_id']}"):
            st.session_state[SS_MENU_PICK] = {"menu": menu, "store_id": r["store_id"],
                                              "name": r["name"]}
            st.session_state["menu_pick_store"] = r["store_id"]
            go_to_plan(r)   # 필요하면 등록하고 바로 넘어간다
            st.rerun()


if _tab == "메뉴로 찾기":
    st.caption("메뉴 이름을 입력하면, 블로그 후기에서 해당 메뉴가 확인된 인근 매장을 궁합 점수 순으로 보여 드립니다.")

    with st.form("menu_search_form", border=False):
        f1, f2 = st.columns([2, 3])
        menu_name = f1.text_input("메뉴 이름", placeholder="예: 두바이 초콜릿", key="menu_name")
        menu_tiers = f2.multiselect(
            "관련 업종 (메뉴 성격에 맞게 고르면 더 정확합니다)",
            TIER_LABELS, default=TIER_LABELS, key="menu_tiers",
        )
        go = st.form_submit_button("찾기", type="primary")

    if go:
        menu = (menu_name or "").strip()
        if not menu:
            st.warning("메뉴 이름을 입력해 주십시오.")
        elif not menu_tiers:
            st.warning("업종을 하나 이상 선택해 주십시오.")
        else:
            cands = load_scored_candidates()
            pool = cands[cands["tier"].isin(menu_tiers)] if not cands.empty else cands
            if pool.empty:
                st.session_state[SS_MENU_RESULT] = {"menu": menu, "res": None}
            else:
                rows = tuple(tuple(r.items()) for r in pool[POOL_COLS]
                             .head(menu_search.MAX_STORES).to_dict("records"))
                with st.spinner(f"궁합 상위 매장 {len(rows)}곳의 후기에서 '{menu}'를 찾는 중… (10초 내외)"):
                    try:
                        res = run_menu_search(menu, rows)
                    except Exception as e:
                        st.error("검색하지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
                        st.caption(f"오류 내용: {e}")
                        res = None
                st.session_state[SS_MENU_RESULT] = {"menu": menu, "res": res}
                st.session_state.pop("menu_pick_store", None)

    found = st.session_state.get(SS_MENU_RESULT)
    if found and found.get("res") is None and found.get("menu"):
        st.caption("조건에 맞는 후보가 없습니다. 업종 선택 범위를 넓혀 주십시오.")
    elif found and found.get("res"):
        menu, res = found["menu"], found["res"]
        note = f" · {res['errors']}곳은 검색이 안 됐습니다" if res["errors"] else ""
        st.caption(f"'{menu}' — 궁합 상위 매장 {res['searched']}곳 중 후기에서 확인된 곳 "
                   f"{len(res['hits'])}곳{note}")
        st.caption(f"정보 출처 · 가게: {STORE_SOURCE} · 메뉴: 네이버 블로그 후기"
                   + (f" (검색 {res['at']})" if res.get("at") else "")
                   + " · 후기는 과거 게시물일 수 있으므로 현재 판매 여부는 매장 확인이 필요합니다")

        if not res["top"]:
            st.info("후기에서 해당 메뉴가 확인된 매장이 없습니다. 메뉴명을 보다 일반적인 표현으로 "
                    "변경하거나(예: 「두바이 쫀득쿠키」→「두바이 초콜릿」) 업종 범위를 넓혀 주십시오.")
        for i, r in enumerate(res["top"], 1):
            _menu_card(i, r, menu)

        if res["misses"]:
            with st.expander(f"언급이 확인되지 않은 곳 {len(res['misses'])}곳"):
                st.caption("블로그 언급이 없더라도 판매 중일 수 있습니다. 지도에서 확인하시기 바랍니다.")
                for r in res["misses"]:
                    st.markdown(f"- **{r['name']}** ({r.get('tier')}, {int(r['distance_m'])}m, "
                                f"{fit_label(r['score'])}) — "
                                f"[네이버 지도](https://map.naver.com/p/search/{quote(r['name'])})")

        # 고른 가게 — 기존 흐름(등록 여부 확인 → 등록 → 기획안 생성)을 그대로 탄다
        pick_id = st.session_state.get("menu_pick_store")
        picked = next((r for r in res["hits"] if r["store_id"] == pick_id), None)
        if picked:
            st.divider()
            st.markdown(f"#### {picked['name']} · 메뉴 「{menu}」")
            render_next_step(
                picked["name"],
                guess_industry_category(picked.get("category_m"), picked.get("category_s")),
                picked.get("lat"), picked.get("lng"),
                key_prefix="menu", address=picked.get("address"),
            )