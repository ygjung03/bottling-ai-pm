"""
바틀링 AI PM — 진입점 (홈)

실행: streamlit run app/main.py

[10/14 홈 개편] 소개 화면 → 대표님 대시보드
  예전 홈은 서비스 소개(히어로 · 기능 카드 4개)였다. 실제로 쓰는 사람은 대표님
  한 분이라, 들어오자마자 「다음에 할 일」이 보이게 바꿨다.

    다음 할 일        AI 추천 받기 / 정해 둔 매장이 있어요 → 파트너 추천
    진행 중인 협업     협력사별 단계 (기획 → 제안 보냄 → 답 받음 → 진행)
    다가오는 근처 행사  events, 오늘부터 60일
    지금 뚝섬         market_context 최신값 + 날씨 기준 맥주 + 공략 시간대

  디자인 시안: 「바틀링 AI PM 웹 디자인」 캔버스의 「앱 · 홈」.
  값이 없으면 지어내지 않고 「-」와 이유를 보인다.
"""
import base64
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import _path  # noqa: F401  (프로젝트 루트를 sys.path 에 추가)
import streamlit as st

from app.auth import is_owner, login_form
from app.theme import BASE_CSS, open_partner_tab, render_topnav

st.set_page_config(page_title="바틀링 AI PM", page_icon="🍺",
                   layout="wide", initial_sidebar_state="collapsed")

KST = timezone(timedelta(hours=9))
WEEKDAY = "월화수목금토일"
MASCOT = Path(__file__).parent / "img" / "mascot.png"   # 대표님이 만든 캐릭터

HOME_CSS = """
<style>
.block-container { padding-bottom: 3rem; max-width: 1240px; }

.home-date { font-size: 0.95rem; color: #5F5F5A; margin: 0.4rem 0 0.5rem; }
.home-title {
    font-family: 'Pretendard', sans-serif; font-size: 2.6rem; font-weight: 900;
    line-height: 1.2; letter-spacing: -0.035em; color: var(--ink); margin: 0 0 1.6rem;
}

/* 다음 할 일 — 검은 카드 */
.st-key-home_hero {
    background: #0E0E0E; border-radius: 28px; padding: 2.4rem 2.6rem;
    margin-bottom: 1.6rem;
}
.hero-chip {
    display: inline-block; padding: 0.35rem 0.8rem; border-radius: 999px;
    background: #2A2A27; color: #E8A33D; font-size: 0.82rem; font-weight: 700;
    margin-bottom: 1rem;
}
.hero-text {
    font-family: 'Pretendard', sans-serif; color: #FFFFFF; font-size: 1.9rem;
    font-weight: 900; line-height: 1.3; letter-spacing: -0.03em; margin-bottom: 1.4rem;
}
.hero-img { display: flex; justify-content: flex-end; align-items: center; height: 100%; }
.hero-img img { width: 100%; max-width: 250px; height: auto; }
/* 버튼 세 개 — 첫 번째만 흰 바탕, 나머지는 테두리 */
.st-key-hero_go button, .st-key-hero_own button, .st-key-hero_menu button {
    min-height: 52px; padding: 0 1.4rem; border-radius: 999px; width: 100%;
    background: transparent; border: 1px solid #3A3A36; color: #FFFFFF;
}
.st-key-hero_go button { background: #FFFFFF; border-color: #FFFFFF; }
.st-key-hero_go button p { color: #0E0E0E !important; font-weight: 700 !important; }
.st-key-hero_own button p, .st-key-hero_menu button p { color: #FFFFFF !important; font-weight: 500 !important; }
.st-key-hero_go button:hover { background: #ECECE8; border-color: #ECECE8; }
.st-key-hero_own button:hover, .st-key-hero_menu button:hover { border-color: #8A8A84; background: #1A1A18; }
.st-key-hero_go button:focus, .st-key-hero_own button:focus, .st-key-hero_menu button:focus { box-shadow: none; }
.st-key-hero_go button p, .st-key-hero_own button p, .st-key-hero_menu button p { white-space: nowrap; }

/* 흰 카드 — 세 카드가 같은 머리 · 같은 줄 높이 · 같은 바닥 줄을 쓴다 (10/14 정리)
   두 카드가 나란히 설 때 높이를 맞추려고 열 안의 감싸개까지 100% 로 늘리고,
   바닥 줄(.card-foot 가 든 마지막 칸)을 margin-top:auto 로 맨 아래에 붙인다. */
.st-key-home_row [data-testid="stColumn"] { display: flex; flex-direction: column; }
.st-key-home_row [data-testid="stColumn"] [data-testid="stVerticalBlockBorderWrapper"]:has(.st-key-home_ongoing, .st-key-home_events) {
    flex: 1 1 auto; display: flex; flex-direction: column;
}
.st-key-home_row [data-testid="stColumn"] [data-testid="stVerticalBlockBorderWrapper"]:has(.st-key-home_ongoing, .st-key-home_events) > div {
    flex: 1 1 auto; display: flex; flex-direction: column;
}
.st-key-home_ongoing, .st-key-home_events, .st-key-home_now {
    background: #FFFFFF; border-radius: 24px; padding: 1.75rem 2rem 1.35rem;
    height: 100%; gap: 0 !important; box-sizing: border-box;
}
/* Streamlit 이 칸 너비를 카드 바깥 너비(px)로 박아 패딩만큼 넘친다 — 안쪽 기준으로 되돌린다 */
.st-key-home_ongoing > div, .st-key-home_events > div, .st-key-home_now > div,
.st-key-home_ongoing [data-testid="stMarkdown"], .st-key-home_events [data-testid="stMarkdown"],
.st-key-home_now [data-testid="stMarkdown"] { width: 100% !important; }
.st-key-home_ongoing > div:last-child, .st-key-home_events > div:last-child { margin-top: auto; }
.card-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px;
             margin-bottom: 1.25rem; }
.card-title { font-size: 1.25rem; font-weight: 800; letter-spacing: -0.02em; color: var(--ink); }
.card-sub { font-size: 0.82rem; color: #6B6B66; }
.card-foot { display: flex; justify-content: space-between; align-items: center; gap: 12px;
             padding-top: 0.9rem; margin-top: 0.4rem; border-top: 1px solid #ECECE8;
             font-size: 0.82rem; color: #6B6B66; min-height: 2.6rem; }
.st-key-ongoing_foot, .st-key-events_foot {
    flex-direction: row !important; align-items: center !important; gap: 12px !important;
    padding-top: 0.9rem; margin-top: 0.4rem; border-top: 1px solid #ECECE8; min-height: 3.2rem;
}
.st-key-ongoing_foot > div, .st-key-events_foot > div,
.st-key-ongoing_foot [data-testid="stMarkdown"], .st-key-events_foot [data-testid="stMarkdown"],
.st-key-ongoing_foot [data-testid="stPageLink"] {
    width: auto !important; flex: 0 0 auto !important; height: auto !important; margin: 0 !important;
}
.st-key-ongoing_foot > div:last-child { margin-left: auto !important; }
.st-key-ongoing_foot [data-testid="stMarkdownContainer"], .st-key-events_foot [data-testid="stMarkdownContainer"] { margin: 0 !important; }
.st-key-ongoing_foot p, .st-key-events_foot p { font-size: 0.82rem !important; color: #6B6B66; margin: 0 !important; line-height: 1.4 !important; }
.st-key-ongoing_foot div[data-testid="stPageLink"] a { padding: 0 !important; min-height: 0 !important; background: transparent !important; }
.st-key-ongoing_foot div[data-testid="stPageLink"] a p { color: var(--ink) !important; font-weight: 600 !important; }
.st-key-ongoing_foot div[data-testid="stPageLink"] a:hover p { text-decoration: underline; }

/* 협업 단계 막대 */
.stage-bar { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 4px; margin-bottom: 0.5rem; }
.stage-bar div { font-size: 0.82rem; color: #6B6B66; }
.stage-bar span { display: block; height: 4px; border-radius: 2px; background: #ECECE8; margin-bottom: 10px; }
.stage-bar .on { color: var(--ink); }
.stage-bar .on span { background: #111110; }
.stage-bar b { font-weight: 700; margin-left: 4px; font-variant-numeric: tabular-nums; }
/* 행사 목록은 단계 막대 높이만큼 내려 두 목록의 줄을 맞춘다 */
.events-list { margin-top: 3.95rem; }

/* 목록 한 줄 — 두 카드 모두 72px */
.item { height: 72px; display: flex; align-items: center; gap: 16px; border-top: 1px solid #ECECE8; }
.item:first-child { border-top: none; }
.item-body { flex: 1; min-width: 0; }
.item-name { font-size: 1rem; font-weight: 700; letter-spacing: -0.01em; color: var(--ink);
             white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.item-meta { font-size: 0.82rem; color: #6B6B66; margin-top: 3px;
             white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.status { display: flex; align-items: center; gap: 7px; white-space: nowrap;
          font-size: 0.82rem; font-weight: 600; color: #6B6B66; }
.status::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: #B5B5B0; }
.status.s1::before { background: #6B6B66; }
.status.s2 { color: var(--ink); }
.status.s2::before { background: #F5B800; }
.status.s3 { color: var(--ink); }
.status.s3::before { background: #111110; }
.empty { font-size: 0.9rem; color: #6B6B66; padding: 1rem 0; line-height: 1.6; }

.ev-date { width: 52px; flex: none; font-variant-numeric: tabular-nums; }
.ev-date b { display: block; font-size: 1.05rem; font-weight: 800; letter-spacing: -0.02em; color: var(--ink); }
.ev-date span { font-size: 0.75rem; color: #6B6B66; }
.live { display: inline-block; font-size: 0.7rem; font-weight: 700; color: var(--ink);
        background: #FFF4CC; border-radius: 4px; padding: 1px 6px; margin-right: 6px; }

/* 지금 뚝섬 — 타일 대신 위 검은 선 + 세로 칸 */
.dot-live { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #2BB673;
            margin-right: 6px; box-shadow: 0 0 0 3px rgba(43,182,115,.15); vertical-align: 1px; }
.board { display: grid; grid-template-columns: 1fr 1fr 1.15fr 1.25fr; border-top: 1px solid #111110; }
.cell { padding: 1.1rem 1.5rem 0.4rem; border-left: 1px solid #ECECE8; min-width: 0; }
.cell:first-child { border-left: none; padding-left: 0; }
.cell-lab { font-size: 0.82rem; color: #6B6B66; margin-bottom: 0.75rem; }
.cell-val { font-size: 1.9rem; font-weight: 800; letter-spacing: -0.03em; line-height: 1; color: var(--ink);
            font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cell-val small { font-size: 0.95rem; font-weight: 600; color: #6B6B66; margin-left: 4px; letter-spacing: 0; }
.cell-note { font-size: 0.82rem; color: #6B6B66; margin-top: 0.9rem; }
.beer { display: flex; align-items: center; gap: 8px; }
.beer::before { content: ""; flex: none; width: 10px; height: 22px; border-radius: 2px; background: #F5B800; }
.meter { display: flex; gap: 3px; margin-top: 0.9rem; }
.meter i { flex: 1; height: 6px; background: #ECECE8; }
.meter i.on { background: #111110; }
.meter-lab { display: flex; justify-content: space-between; font-size: 0.68rem; color: #A3A39E; margin-top: 6px; }
.bars { display: flex; align-items: flex-end; gap: 4px; height: 44px; margin-top: 0.75rem; }
.bars div { flex: 1; background: #ECECE8; border-radius: 2px 2px 0 0; min-height: 2px; }
.bars div.pk { background: #111110; }
.bars-lab { display: flex; gap: 4px; font-size: 0.65rem; color: #A3A39E; margin-top: 5px; }
.bars-lab span { flex: 1; text-align: center; }
.st-key-home_now .card-foot { margin-top: 1.1rem; }

.login-title { font-size: 2.1rem; font-weight: 800; color: var(--ink); margin: 0.6rem 0 0.2rem 0; text-align: center; }
</style>
"""
st.markdown(BASE_CSS, unsafe_allow_html=True)
st.markdown(HOME_CSS, unsafe_allow_html=True)


# ───────────────────────── 데이터 ─────────────────────────

def _client():
    from db.client import get_client
    return get_client()


def _day(iso: str | None) -> str:
    """'2026-10-23' → '10/23(금)'"""
    if not iso:
        return ""
    d = date.fromisoformat(str(iso)[:10])
    return f"{d.month}/{d.day}({WEEKDAY[d.weekday()]})"


STAGES = ["기획", "제안 보냄", "답 받음", "진행"]
BANDS = ["00-06", "06-11", "11-14", "14-17", "17-21", "21-24"]   # sales_profile 시간대 키
CONGESTION = ["여유", "보통", "약간 붐빔", "붐빔"]                  # 서울 실시간 도시데이터 단계


def _has_form(partner: dict) -> bool:
    """구글 폼이 들어왔는가 — 2_기획안_생성.has_form 과 같은 기준."""
    return any(partner.get(k) for k in ("available_slots", "blockers", "sns_channel"))


@st.cache_data(ttl=120)
def load_collabs() -> list[dict] | None:
    """
    협력사별 협업 단계. 기획안이 하나라도 있는 협력사만, 최근 것부터.

      진행      실행할 안을 골랐거나(final_option) 실행일을 적었다
      답 받음    협력사 구글 폼이 들어왔다
      제안 보냄  보관함에서 보낸 안을 정했다 (sent_option)
      기획      기획안만 있다
    """
    try:
        cli = _client()
        plans = (cli.table("plans")
                 .select("id,partner_id,target_date,adopted_option,sent_option,"
                         "final_option,executed_from,final_output")
                 .order("id", desc=True).limit(300).execute().data or [])
        partners = {p["id"]: p for p in (
            cli.table("partners")
            .select("id,name,available_slots,blockers,sns_channel")
            .execute().data or [])}
    except Exception:
        return None

    by_partner: dict[int, list[dict]] = {}
    for pl in plans:
        if pl.get("partner_id") in partners:
            by_partner.setdefault(pl["partner_id"], []).append(pl)

    out = []
    for pid, pls in by_partner.items():          # plans 가 최신순이라 dict 순서도 최신순
        partner = partners[pid]
        if any(p.get("final_option") or p.get("executed_from") for p in pls):
            stage = 3
        elif _has_form(partner):
            stage = 2
        elif any(p.get("sent_option") for p in pls):
            stage = 1
        else:
            stage = 0

        # 보일 안 — 실행 > 보냄 > 담음 > 최신 기획안의 첫 안
        def pick(p):
            ids = [x for x in (p.get("final_option"), p.get("sent_option"),
                               (p.get("adopted_option") or "").split(",")[0]) if x]
            return ids[0] if ids else None
        lead = next((p for p in pls if p.get("final_option")), None) \
            or next((p for p in pls if p.get("sent_option")), None) or pls[0]
        items = (lead.get("final_output") or {}).get("안") or []
        aid = pick(lead)
        item = next((i for i in items if i.get("안_id") == aid), items[0] if items else {})
        out.append({"name": partner.get("name") or "-", "stage": stage,
                    "date": _day(lead.get("target_date")),
                    "menu": item.get("메뉴명") or ""})
    return out


@st.cache_data(ttl=600)
def load_events(days: int = 60, limit: int = 4) -> list[dict] | None:
    """오늘부터 days 일 안의 행사. 몇 달짜리 전시는 날짜를 고를 근거가 안 되어 뺀다."""
    today = datetime.now(KST).date()
    try:
        rows = (_client().table("events")
                .select("title,place,start_date,end_date,source")
                .gte("end_date", today.isoformat())
                .lte("start_date", (today + timedelta(days=days)).isoformat())
                .limit(200).execute().data or [])
    except Exception:
        return None
    seen, out = set(), []
    for e in rows:
        s = date.fromisoformat(e["start_date"])
        t = date.fromisoformat(e.get("end_date") or e["start_date"])
        if (t - s).days > 60 or e["title"] in seen:
            continue
        seen.add(e["title"])
        out.append({**e, "_key": max(s, today)})
    out.sort(key=lambda e: e["_key"])
    return out[:limit]


@st.cache_data(ttl=300)
def load_now() -> dict | None:
    """지금 뚝섬 — 실시간 도시데이터 최신값, 날씨 기준 맥주, 호프 매출이 몰리는 시간대."""
    try:
        cli = _client()
        station = (cli.table("market_context")
                   .select("collected_at,temp,precpt_type,congestion_level")
                   .eq("spot", "뚝섬역").order("collected_at", desc=True)
                   .limit(1).execute().data or [])
        park = (cli.table("market_context")
                .select("collected_at,congestion_level")
                .eq("spot", "뚝섬한강공원").order("collected_at", desc=True)
                .limit(1).execute().data or [])
        beers = (cli.table("beers").select("name,style,abv,is_fixed")
                 .is_("valid_to", "null").order("is_fixed", desc=True)
                 .order("price_per_ml").execute().data or [])
        sales = (cli.table("sales_profile").select("quarter,industry_name,timeband_ratio")
                 .eq("dong_name", "자양3동").ilike("industry_name", "%호프%")
                 .order("quarter", desc=True).limit(1).execute().data or [])
    except Exception:
        return None

    st_row = station[0] if station else {}
    pk_row = park[0] if park else {}
    temp = st_row.get("temp")
    rain = (st_row.get("precpt_type") or "없음") not in ("없음", "", None)

    # 날씨별 선호 (대표님, 8/31): 비·추움 → 흑맥주 / 더움 → 라거
    beer, why = None, ""
    if temp is not None:
        dark = rain or float(temp) < 15
        want = ("스타우트", "포터", "흑", "다크") if dark else ("라거", "필스너")
        beer = next((b["name"] for b in beers
                     if any(w in (b.get("style") or "") for w in want)
                     and float(b.get("abv") or 0) > 0), None)
        if rain:
            why = "비 오는 날 → 흑맥주"
        elif dark:
            why = "15°C 아래 → 흑맥주"
        else:
            why = "15°C 이상 · 비 없음 → 라거"

    # 시간대 6칸 (00-06 … 21-24) — 막대 그래프와 가장 큰 칸
    bands, band, band_pct = [], None, None
    if sales and sales[0].get("timeband_ratio"):
        tb = sales[0]["timeband_ratio"]
        bands = [(k, float(tb.get(k) or 0)) for k in BANDS]
        k, v = max(bands, key=lambda x: x[1])
        if v > 0:
            band, band_pct = k.replace("-", "–"), round(v * 100)

    at = st_row.get("collected_at") or pk_row.get("collected_at")
    return {
        "congestion": pk_row.get("congestion_level") or st_row.get("congestion_level"),
        "temp": temp, "rain": rain, "beer": beer, "beer_why": why,
        "precpt": st_row.get("precpt_type"),
        "bands": bands, "band": band, "band_pct": band_pct,
        "band_src": sales[0]["quarter"] if sales else None,
        "at": datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(KST)
              .strftime("%m/%d %H:%M") if at else None,
    }


def _mascot_tag() -> str:
    try:
        b64 = base64.b64encode(MASCOT.read_bytes()).decode()
        return f'<div class="hero-img"><img src="data:image/png;base64,{b64}" alt="바틀링 마스코트"></div>'
    except Exception:
        return ""


# ───────────────────────── 화면 ─────────────────────────

if not is_owner():
    st.write("")
    _, mid, _ = st.columns([1, 1.1, 1])
    with mid:
        st.write("")
        st.markdown('<div class="login-title">바틀링 AI PM</div>', unsafe_allow_html=True)
        st.caption("소상공인 협업 기획 자동화")
        st.write("")
        with st.container(border=True):
            login_form()
        st.write("")
        st.caption("협력사 정보 입력은 전달받으신 링크로 접속해 주세요.")
    st.stop()

# ── 로그인 후 ──
render_topnav("logout")

today = datetime.now(KST).date()
st.markdown(f'<div class="home-date">{today.month}월 {today.day}일 {WEEKDAY[today.weekday()]}요일</div>'
            '<div class="home-title">대표님, 다음 협업을<br>정해 볼까요?</div>',
            unsafe_allow_html=True)

# 다음 할 일
with st.container(key="home_hero"):
    left, right = st.columns([3, 1.2], vertical_alignment="center")
    with left:
        st.markdown('<span class="hero-chip">다음 할 일</span>'
                    '<div class="hero-text">기간만 고르세요.<br>날짜 · 매장 · 메뉴는 AI가 제안합니다.</div>',
                    unsafe_allow_html=True)
        # 세 길 모두 파트너 추천 화면으로 가되, 처음 열 탭이 다르다
        b1, b2, b3, _ = st.columns([1, 1.25, 1, 0.5], gap="small")
        with b1:
            with st.container(key="hero_go"):
                if st.button("AI 추천 받기  →", use_container_width=True):
                    open_partner_tab("추천받기")
        with b2:
            with st.container(key="hero_own"):
                if st.button("정해 둔 매장이 있어요", use_container_width=True):
                    open_partner_tab("직접 지정")
        with b3:
            with st.container(key="hero_menu"):
                if st.button("메뉴로 찾기", use_container_width=True):
                    open_partner_tab("메뉴로 찾기")
    with right:
        st.markdown(_mascot_tag(), unsafe_allow_html=True)

def _foot(left: str, right: str = "") -> str:
    return f'<div class="card-foot"><span>{left}</span>{right}</div>'


with st.container(key="home_row"):
    col_a, col_b = st.columns([3, 2], gap="medium")

# 진행 중인 협업
with col_a:
    with st.container(key="home_ongoing"):
        collabs = load_collabs()
        counts = [sum(1 for c in (collabs or []) if c["stage"] == i) for i in range(4)]
        bar = "".join(
            f'<div class="{"on" if counts[i] else ""}"><span></span>{name}<b>{counts[i]}</b></div>'
            for i, name in enumerate(STAGES))
        head = ('<div class="card-head"><span class="card-title">진행 중인 협업</span>'
                f'<span class="card-sub">최근 {min(len(collabs or []), 4)}곳</span></div>'
                f'<div class="stage-bar">{bar}</div>')
        if collabs is None:
            body = '<div class="empty">협업 정보를 불러오지 못했습니다. 잠시 뒤 새로고침해 주십시오.</div>'
        elif not collabs:
            body = ('<div class="empty">아직 만든 기획안이 없습니다.<br>'
                    '위의 「AI 추천 받기」로 첫 협업을 시작해 보십시오.</div>')
        else:
            body = ""
            for c in collabs[:4]:
                meta = " · ".join(x for x in (c["date"], c["menu"]) if x)
                body += (f'<div class="item"><div class="item-body"><div class="item-name">{c["name"]}</div>'
                         f'<div class="item-meta">{meta}</div></div>'
                         f'<span class="status s{c["stage"]}">{STAGES[c["stage"]]}</span></div>')
        st.markdown(head + f'<div>{body}</div>', unsafe_allow_html=True)
        # 바닥 줄 — 링크는 page_link 여야 로그인 세션이 이어진다 (<a href> 는 새로 고침).
        # 보관함은 협력사별이라 기획안 생성 화면 오른쪽 위 「보관함」에서 연다.
        with st.container(key="ongoing_foot"):
            st.markdown(f"협업 중인 매장 {len(collabs or [])}곳")
            st.page_link("pages/2_기획안_생성.py", label="보관함 전체 보기 →")

# 다가오는 근처 행사
with col_b:
    with st.container(key="home_events"):
        events = load_events()
        head = ('<div class="card-head"><span class="card-title">다가오는 근처 행사</span>'
                '<span class="card-sub">60일 이내</span></div>')
        if events is None:
            body = '<div class="empty">행사 정보를 불러오지 못했습니다.</div>'
        elif not events:
            body = '<div class="empty">앞으로 60일 안에 수집된 행사가 없습니다.</div>'
        else:
            body = ""
            for e in events:
                s = date.fromisoformat(e["start_date"])
                t = date.fromisoformat(e.get("end_date") or e["start_date"])
                place = e.get("place") or ""
                if s >= today:
                    box_d, box_s = s, WEEKDAY[s.weekday()]
                    meta = " · ".join(x for x in (f"~{t.month}/{t.day}" if t != s else "", place) if x)
                else:
                    box_d, box_s = t, "까지"
                    meta = '<span class="live">진행 중</span>' + place
                body += (f'<div class="item"><div class="ev-date"><b>{box_d.month}/{box_d.day}</b>'
                         f'<span>{box_s}</span></div><div class="item-body">'
                         f'<div class="item-name" title="{e["title"]}">{e["title"]}</div>'
                         f'<div class="item-meta">{meta}</div></div></div>')
        st.markdown(head + f'<div class="events-list">{body}</div>', unsafe_allow_html=True)
        with st.container(key="events_foot"):
            st.markdown("출처 · 서울시 · 광진구청 · 네이버 뉴스")

st.write("")

# 지금 뚝섬
with st.container(key="home_now"):
    now = load_now() or {}
    at = (f'<span class="dot-live"></span>{now["at"]} 관측 · ' if now.get("at") else "")
    st.markdown(f'<div class="card-head"><span class="card-title">지금 뚝섬</span>'
                f'<span class="card-sub">{at}서울 실시간 도시데이터</span></div>',
                unsafe_allow_html=True)

    def cell(label, value, extra=""):
        v = value if value not in (None, "") else "-"
        return (f'<div class="cell"><div class="cell-lab">{label}</div>'
                f'<div class="cell-val">{v}</div>{extra}</div>')

    # 인파 — 4단계 중 지금 위치
    cong = now.get("congestion")
    lvl = CONGESTION.index(cong) if cong in CONGESTION else -1
    meter = ('<div class="meter">' + "".join(f'<i class="{"on" if i == lvl else ""}"></i>' for i in range(4))
             + '</div><div class="meter-lab">' + "".join(f"<span>{c}</span>" for c in CONGESTION) + "</div>")

    # 기온
    temp = now.get("temp")
    precpt = now.get("precpt")
    t_val = f'{float(temp):.0f}<small>°C</small>' if temp is not None else None
    t_note = f'<div class="cell-note">{"강수 없음" if precpt in (None, "", "없음") else precpt}</div>'

    # 맥주 — 이름 앞 노란 막대, 아래에 고른 규칙
    beer = f'<span class="beer">{now["beer"]}</span>' if now.get("beer") else None
    b_note = f'<div class="cell-note">{now["beer_why"]}</div>' if now.get("beer_why") else ""

    # 시간대 — 6칸 막대, 가장 큰 칸만 검게
    bands = now.get("bands") or []
    top = max((v for _, v in bands), default=0)
    if top > 0:
        bars = ('<div class="bars">' + "".join(
            f'<div class="{"pk" if v == top else ""}" style="height:{v / top * 100:.0f}%"></div>'
            for _, v in bands) + '</div><div class="bars-lab">'
            + "".join(f"<span>{int(k[:2])}</span>" for k, _ in bands) + "</div>")
        b_val = f'{now["band"]}<small>시 · {now["band_pct"]}%</small>'
    else:
        bars, b_val = "", None

    st.markdown(
        '<div class="board">'
        + cell("한강공원 인파", cong, meter if lvl >= 0 else "")
        + cell("뚝섬역 기온", t_val, t_note if temp is not None else "")
        + cell("오늘 내놓을 맥주", beer, b_note)
        + cell("호프 매출이 몰리는 시간", b_val, bars)
        + '</div>', unsafe_allow_html=True)
    if not now:
        st.caption("실시간 정보를 불러오지 못했습니다. 잠시 뒤 새로고침해 주십시오.")
    elif now.get("band_src"):
        st.markdown(_foot(f"시간대 비중 · 자양3동 호프 매출 · {now['band_src']}"), unsafe_allow_html=True)