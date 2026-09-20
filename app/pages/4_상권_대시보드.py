"""T24b — 상권 대시보드 (4-4)

구성:
0. 협업 후보 지도 (nearby_stores 제과·베이커리/카페, 바틀링 반경 1km) — 대표님 보고용, 위치만 찍는 지도 대신
1. 현재 혼잡도 · 추정 인구 (뚝섬한강공원 · 뚝섬역)
2. 12시간 예측 라인 차트 (두 지점)
2b. 요일×시간대 인구 히트맵 (T25 중간분석보고서와 동일 집계)
3. 음식업 결제 추세 (뚝섬역 기준 — 한강공원은 상권 데이터 없음)
4. 인근 행사 리스트 (반경 3km · 향후 30일)
"""

import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Streamlit이 app/pages/*.py를 실행할 때는 프로젝트 루트가 sys.path에 없어서
# db.client 같은 최상위 모듈을 못 찾는다. 루트를 직접 추가해서 해결한다.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

from app.auth import require_owner
from app.ui import sidebar
from db.client import get_client

st.set_page_config(page_title="상권 대시보드", page_icon="📊", layout="wide")

# [중요] 이 페이지만 인증 검사가 빠져 있었다 (9/9 머지 시 확인).
#
# Streamlit 멀티페이지는 URL 직접 접근이 된다. 주소창에
# /상권_대시보드 를 치면 사이드바를 거치지 않고 이 파일이 실행된다.
# 그래서 각 페이지가 첫머리에서 매번 검사해야 한다 (명세서 4-0-1).
# 나머지 네 페이지는 모두 하고 있다.
require_owner()
sidebar("상권 대시보드")

# ── 팔레트 (라이트, BI 툴 톤) ─────────────────────────────────
INK = "#1F2933"
INK_MUTED = "#6B7280"
INK_FAINT = "#9CA3AF"
LINE = "#E5E7EB"
SURFACE = "#FFFFFF"

ACCENT_PARK = "#2F6FED"      # 뚝섬한강공원 — 블루
ACCENT_STATION = "#F59E0B"   # 뚝섬역 — 앰버

CONGEST_COLOR = {
    "여유": "#22C55E",
    "보통": "#3B82F6",
    "약간 붐빔": "#F97316",
    "붐빔": "#EF4444",
}
CONGEST_FRAC = {"여유": 0.25, "보통": 0.5, "약간 붐빔": 0.75, "붐빔": 1.0}

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&family=JetBrains+Mono:wght@500;600&display=swap');

html, body, [class*="css"], .stMarkdown {{ font-family: 'Noto Sans KR', -apple-system, sans-serif; }}
[data-testid="stAppViewContainer"] {{ background: #F4F6FA; }}

.bt-crumb {{ color: {INK_FAINT}; font-size: 0.8rem; margin-bottom: 0.15rem; }}
.bt-title {{ font-size: 1.4rem; font-weight: 700; color: {INK}; margin-bottom: 1.4rem; }}

.bt-section-title {{ font-size: 1rem; font-weight: 700; color: {INK}; margin: 1.7rem 0 0.8rem; }}
.bt-section-sub {{ color: {INK_MUTED}; font-size: 0.82rem; margin: -0.55rem 0 0.9rem; }}

.bt-card {{
  background: {SURFACE};
  border: 1px solid {LINE};
  border-radius: 16px;
  padding: 1.3rem 1.5rem;
  box-shadow: 0 1px 2px rgba(15,23,42,0.04), 0 10px 24px -18px rgba(15,23,42,0.18);
}}

.bt-card-head {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.9rem; }}
.bt-spot-name {{ font-size: 0.92rem; font-weight: 700; color: {INK}; }}
.bt-pill {{ display: inline-block; padding: 0.2rem 0.65rem; border-radius: 999px; font-size: 0.76rem; font-weight: 700; color: #fff; }}

.bt-stat-value {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 1.7rem;
  font-weight: 700;
  color: {INK};
  white-space: nowrap;
  line-height: 1.1;
}}
.bt-stat-label {{ font-size: 0.76rem; color: {INK_FAINT}; margin-bottom: 0.25rem; }}

.bt-track {{ width: 100%; height: 6px; background: #EEF1F5; border-radius: 999px; overflow: hidden; margin: 0.7rem 0 0.9rem; }}
.bt-track-fill {{ height: 100%; border-radius: 999px; }}

.bt-caption {{ color: {INK_MUTED}; font-size: 0.82rem; line-height: 1.5; }}
.bt-timestamp {{ display: flex; align-items: center; font-family: 'JetBrains Mono', monospace; color: {INK_FAINT}; font-size: 0.7rem; margin-top: 0.6rem; cursor: default; }}

.bt-live-dot {{
  display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  background: var(--bt-live-color, #22C55E); margin-right: 0.45rem; flex: none;
  animation: bt-pulse 1.8s ease-in-out infinite;
}}
@keyframes bt-pulse {{
  0%   {{ box-shadow: 0 0 0 0 color-mix(in srgb, var(--bt-live-color, #22C55E) 55%, transparent); }}
  70%  {{ box-shadow: 0 0 0 6px color-mix(in srgb, var(--bt-live-color, #22C55E) 0%, transparent); }}
  100% {{ box-shadow: 0 0 0 0 color-mix(in srgb, var(--bt-live-color, #22C55E) 0%, transparent); }}
}}

/* st.container(border=True)로 위젯(지도 등)을 감싸면 래퍼만 빈 박스로 렌더링되는 경우가 있어,
   대신 지도 위젯 자체의 실제 DOM 노드에 카드 스타일(둥근 모서리·그림자)을 직접 입힌다. */
[data-testid="stDeckGlJsonChart"] {{
  border-radius: 16px;
  overflow: hidden;
  border: 1px solid {LINE};
  box-shadow: 0 1px 2px rgba(15,23,42,0.04), 0 10px 24px -18px rgba(15,23,42,0.18);
}}

.bt-stale-warn {{
  margin-top: 0.55rem;
  font-size: 0.74rem;
  font-weight: 600;
  color: #B91C1C;
  background: rgba(239,68,68,0.08);
  border: 1px solid rgba(239,68,68,0.25);
  border-radius: 8px;
  padding: 0.4rem 0.6rem;
}}
.bt-note {{ color: {INK_MUTED}; font-size: 0.84rem; margin: -0.3rem 0 0.7rem; }}

.bt-insight {{
  display: flex;
  align-items: center;
  gap: 0.65rem;
  background: linear-gradient(135deg, rgba(47,111,237,0.07), rgba(245,158,11,0.07));
  border: 1px solid rgba(47,111,237,0.18);
  border-radius: 12px;
  padding: 0.85rem 1.15rem;
  margin-bottom: 1.6rem;
  font-size: 0.92rem;
  font-weight: 600;
  color: {INK};
}}
.bt-insight-icon {{ flex: none; color: {ACCENT_PARK}; }}

.bt-change-row {{ margin: 0.35rem 0 0.6rem; font-size: 0.8rem; font-weight: 700; }}
.bt-change-flat {{ color: {INK_FAINT}; font-weight: 500; }}
</style>
""", unsafe_allow_html=True)

SPOTS = [
    {"name": "뚝섬한강공원", "color": ACCENT_PARK},
    {"name": "뚝섬역", "color": ACCENT_STATION},
]

BOTTLING_COORD = (37.5318919, 127.0679483)  # 실측 확정값 (API검증결과 V8 참고, 2026.8.23 정정)

client = get_client()

PLOT_FONT = dict(family="Noto Sans KR, sans-serif", color=INK_MUTED, size=12)


def style_layout(fig, **kwargs):
    fig.update_layout(
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=PLOT_FONT,
        margin=dict(t=16, b=10, l=10, r=10),
        xaxis=dict(gridcolor=LINE, zeroline=False, linecolor=LINE),
        yaxis=dict(gridcolor=LINE, zeroline=False, linecolor=LINE),
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=LINE, font=dict(family="Noto Sans KR, sans-serif", color=INK)),
        **kwargs,
    )
    return fig


def hex_to_rgba(hex_color, alpha):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def relative_time_kr(iso_str):
    """'2026-09-07T17:25:00+00:00' 같은 시각을 '3분 전 갱신' 형태로."""
    if not iso_str:
        return "시각 정보 없음"
    ts = pd.to_datetime(iso_str, utc=True)
    seconds = (pd.Timestamp.now(tz="UTC") - ts).total_seconds()
    if seconds < 60:
        return "방금 갱신"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}분 전 갱신"
    hours = int(minutes // 60)
    if hours < 24:
        return f"{hours}시간 전 갱신"
    return f"{int(hours // 24)}일 전 갱신"


STALE_MINUTES = 60  # 30분 배치 수집 기준 — 한 주기(30분)를 넘겨 두 번째 배치도 놓치면 지연으로 본다


def freshness_status(iso_str):
    """(점 색상, 상대시간 라벨, 지연 여부) — 수집 지연을 점 색과 카드 경고로 드러낸다."""
    if not iso_str:
        return "#9CA3AF", "시각 정보 없음", True
    ts = pd.to_datetime(iso_str, utc=True)
    minutes = (pd.Timestamp.now(tz="UTC") - ts).total_seconds() / 60
    label = relative_time_kr(iso_str)
    if minutes >= STALE_MINUTES:
        return "#EF4444", label, True
    return "#22C55E", label, False


def format_change_badge(pct):
    """전일(약 24시간 전) 대비 변화율 배지. 한국 증권 표기 관례를 따라 상승=빨강, 하락=파랑."""
    if pct is None:
        return '<span class="bt-change bt-change-flat">전일 대비 데이터 축적 중</span>'
    if abs(pct) < 0.5:
        return f'<span class="bt-change" style="color:{INK_FAINT}">→ 전일과 유사</span>'
    color = "#DC2626" if pct > 0 else "#2563EB"
    arrow = "▲" if pct > 0 else "▼"
    return f'<span class="bt-change" style="color:{color}">{arrow} 전일 대비 {abs(pct):.1f}%</span>'


def weather_line(row):
    """
    기온·습도·강수 한 줄.

    한강 상권에서 강수 여부가 방문객 수를 크게 좌우한다(기획서 4장).
    수집은 하고 있었으나 화면에 쓰이지 않았다.

    지점 카드 안에 둔다. 두 지점이 각자 관측값을 가지므로, 한 곳에 모아
    보여주면 어느 지점 값인지 드러나지 않는다.
    """
    t, h, p = row.get("temp"), row.get("humidity"), row.get("precpt_type")
    if t is None:
        return ""
    parts = [f"{t}℃"]
    if h is not None:
        parts.append(f"습도 {h}%")
    # "없음"도 적는다. 빼면 관측이 없는 것인지 비가 안 오는 것인지 구분되지 않는다.
    parts.append("강수 없음" if (not p or p == "없음") else f"☔ {p}")
    return " · ".join(parts)


def sparkline(series, color):
    fig = go.Figure(go.Scatter(
        y=series, mode="lines", line=dict(width=2, color=color),
        fill="tozeroy", fillcolor=hex_to_rgba(color, 0.08),
        hoverinfo="skip",
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=0, b=0, l=0, r=0), height=44,
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        showlegend=False,
    )
    return fig


MAP_HEIGHT = 420
BOTTLING_RADIUS_M = 1000  # T09 반경 점포 조회 기준(API검증결과 V8)과 동일 — 지도에서 그 범위를 그대로 보여준다


def hex_to_rgb_list(hex_color, alpha=255):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return [r, g, b, alpha]


def fit_zoom(lats, lons, map_width_px=1100, map_height_px=MAP_HEIGHT, padding=1.6):
    """점들이 전부 화면에 들어오도록 줌 레벨을 역산한다.
    st.map()의 기본/자동 줌은 실제로는 bounds-fit이 아니라 고정값에 가까워서
    지점이 멀리 떨어져 있으면(뚝섬역↔뚝섬한강공원 약 2.3km) 화면 밖으로 잘렸다 — 그 대체."""
    lat_span = max(max(lats) - min(lats), 0.0008) * padding
    lon_span = max(max(lons) - min(lons), 0.0008) * padding
    TILE = 256
    zoom_lon = math.log2(map_width_px / TILE * 360 / lon_span)
    zoom_lat = math.log2(map_height_px / TILE * 360 / lat_span)
    return max(10, min(16, min(zoom_lon, zoom_lat)))


CANDIDATE_COLOR = {
    "제과·베이커리": "#F59E0B",
    "카페": "#2F6FED",
    "기타": "#9CA3AF",
}


@st.cache_data(ttl=3600)
def load_nearby_candidates():
    """nearby_stores(T09, 841건)에서 상보성 매핑표(명세서 3-3)에 해당하는 협업 후보만 가져온다.
    category_m/category_s의 정확한 원문 표기를 확정 검증하지 않았으므로, 오탈자·표기 차이에
    강건하도록 정확 일치가 아닌 키워드 포함 방식으로 거른다."""
    res = (
        client.table("nearby_stores")
        .select("store_id,name,category_m,category_s,address,lat,lng,distance_m")
        .order("distance_m")
        .limit(1000)
        .execute()
    )
    df = pd.DataFrame(res.data)
    if df.empty:
        return df

    cat_text = (df["category_m"].fillna("") + " " + df["category_s"].fillna(""))
    is_bakery = cat_text.str.contains("제과|빵|도넛|피자")
    is_cafe = cat_text.str.contains("카페|비알코올")
    df = df[is_bakery | is_cafe].copy()

    # 필터링된 df 기준으로 다시 계산 — 원본 마스크와의 인덱스 정렬 문제를 아예 피한다.
    filtered_cat_text = df["category_m"].fillna("") + " " + df["category_s"].fillna("")
    df["candidate_type"] = filtered_cat_text.str.contains("제과|빵|도넛|피자").map(
        {True: "제과·베이커리", False: "카페"}
    )
    return df.dropna(subset=["lat", "lng"])


def render_candidate_map(top_n=40):
    """협업 후보(제과·베이커리/카페) 지도. 단순 위치 표시가 아니라
    '바틀링 반경 1km 안에 실제로 붙을 수 있는 후보가 몇 곳, 어디에 있는지'를 보여준다 —
    T15(추천 엔진) 이전이라 점수는 아직 없고, 거리순 상위 후보만 노출한다."""
    candidates = load_nearby_candidates()

    if candidates.empty:
        st.markdown(
            '<div class="bt-note">nearby_stores에서 제과·베이커리/카페 후보를 찾지 못했습니다. '
            '카테고리 표기가 예상과 다를 수 있어 확인이 필요합니다.</div>',
            unsafe_allow_html=True,
        )
        return

    shown = candidates.head(top_n)

    features = [{
        "name": "바틀링", "lat": BOTTLING_COORD[0], "lon": BOTTLING_COORD[1],
        "color": [31, 41, 51, 230], "radius": 45,
        "label": "바틀링 (기준점)",
    }]
    for _, r in shown.iterrows():
        color_hex = CANDIDATE_COLOR.get(r["candidate_type"], CANDIDATE_COLOR["기타"])
        features.append({
            "name": r["name"], "lat": r["lat"], "lon": r["lng"],
            "color": hex_to_rgb_list(color_hex, 200), "radius": 28,
            "label": f"{r['name']} · {r['candidate_type']} · {int(r['distance_m']):,}m",
        })

    df = pd.DataFrame(features)
    point_layer = pdk.Layer(
        "ScatterplotLayer", data=df,
        get_position="[lon, lat]", get_fill_color="color", get_radius="radius",
        radius_min_pixels=5, radius_max_pixels=32,
        stroked=True, get_line_color=[255, 255, 255, 220], line_width_min_pixels=1.5,
        pickable=True,
    )
    radius_ring = pdk.Layer(
        "ScatterplotLayer",
        data=[{"lat": BOTTLING_COORD[0], "lon": BOTTLING_COORD[1]}],
        get_position="[lon, lat]", get_radius=BOTTLING_RADIUS_M,
        filled=False, stroked=True,
        get_line_color=[47, 111, 237, 140], line_width_min_pixels=1.5,
    )

    lats = [f["lat"] for f in features]
    lons = [f["lon"] for f in features]
    view = pdk.ViewState(
        latitude=sum(lats) / len(lats), longitude=sum(lons) / len(lons),
        zoom=fit_zoom(lats, lons), pitch=0,
    )

    st.pydeck_chart(
        pdk.Deck(
            layers=[radius_ring, point_layer], initial_view_state=view,
            tooltip={"text": "{label}"}, map_style=None,
        ),
        height=MAP_HEIGHT, use_container_width=True,
    )

    legend = " · ".join(
        f'<span style="color:{c}">●</span> {name}'
        for name, c in [("바틀링", "#1F2933"), *CANDIDATE_COLOR.items()][:3]
    )
    st.markdown(
        f'<div class="bt-caption" style="margin-top:0.5rem;">{legend} '
        f'&nbsp;·&nbsp; 파란 원 = 반경 1km(T09 조회 범위) &nbsp;·&nbsp; '
        f'거리순 상위 {len(shown)}곳 표시 (전체 후보 {len(candidates)}곳 중)</div>',
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=300)
def load_latest(spot):
    res = (
        client.table("market_context")
        .select("*")
        .eq("spot", spot)
        .order("collected_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


LEVEL_RANK = {"여유": 0, "보통": 1, "약간 붐빔": 2, "붐빔": 3}


def build_insight():
    """지점별 현재 혼잡도 + 12시간 예측 중 피크 시점을 한 줄 요약으로 만든다.
    LLM을 쓰지 않는 규칙 기반 템플릿 — (4) 컨설턴트 reason 생성 방식과 동일한 원칙."""
    status_parts = []
    peak_candidates = []

    for spot in SPOTS:
        row = load_latest(spot["name"])
        if not row:
            continue

        level = row.get("congestion_level") or "데이터 없음"
        status_parts.append(f"{spot['name']} {level}")

        fc = row.get("forecast_12h") or []
        if not fc:
            continue
        fc_df = pd.DataFrame(fc)
        if fc_df.empty or "min" not in fc_df or "max" not in fc_df:
            continue
        fc_df["mid"] = (fc_df["min"] + fc_df["max"]) / 2
        peak_row = fc_df.loc[fc_df["mid"].idxmax()]
        peak_level = peak_row.get("level") or level
        peak_candidates.append({
            "spot": spot["name"],
            "hour": pd.to_datetime(peak_row["time"]).strftime("%H시"),
            "level": peak_level,
            "rank": LEVEL_RANK.get(peak_level, 0),
        })

    if not status_parts:
        return None

    status_line = " · ".join(status_parts)
    if not peak_candidates:
        return status_line

    best = max(peak_candidates, key=lambda p: p["rank"])
    return f"{status_line} — {best['hour']}경 {best['spot']} {best['level']} 예상"


@st.cache_data(ttl=300)
def load_history(spot, days=14, dedup_cmrcl=False):
    """
    최근 N일 시계열.

    dedup_cmrcl 은 상권(결제) 값을 볼 때만 켠다.

    한 행에 인구와 상권이 함께 들어 있지만 둘은 각자 자기 관측 시각을 가진다.

        collected_at  API 의 PPLTN_TIME   — 인구
        cmrcl_time    CMRCL_TIME          — 상권 (raw 안에 있다)

    인구는 이미 중복이 없다. collected_at 이 곧 인구 관측 시각이고
    UNIQUE (collected_at, spot) 제약이 걸려 있어 DB 가 보장한다.

    상권 시각은 컬럼이 아니라 raw 안에 있어 제약을 걸 수 없다. 그래서
    같은 값이 여러 행에 반복되고, 거르지 않으면 결제 추세선이 실제보다
    촘촘하고 평균이 낮게 나온다 (명세서 6-3 원칙 7 · builder 의 _dedup_cmrcl).

    [주의] 인구에는 켜지 마라. 남의 시계로 내 중복을 판정하는 셈이 된다.
    갱신 주기가 얼마든 무관하게 틀린 조치다.

    raw 를 통째로 받지 않는다. 행당 수십 KB 라 statement timeout 이 난다.
    필요한 것은 CMRCL_TIME 하나뿐이라 PostgREST 의 JSONB 문법으로 뽑는다.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cols = ("collected_at,pay_amt_min,pay_amt_max,"
            "population_min,population_max")
    if dedup_cmrcl:
        cols += ",cmrcl_time:raw->LIVE_CMRCL_STTS->>CMRCL_TIME"

    res = (
        client.table("market_context")
        .select(cols)
        .eq("spot", spot)
        .gte("collected_at", since)
        .order("collected_at", desc=False)
        .execute()
    )
    df = pd.DataFrame(res.data)
    if not dedup_cmrcl or df.empty or "cmrcl_time" not in df:
        return df

    # CMRCL_TIME 이 없는 행은 판단할 수 없으므로 남긴다. 지우면 실제 관측을
    # 잃지만, 남기면 최악의 경우 중복이 하나 섞이는 데 그친다.
    dup = df["cmrcl_time"].notna() & df.duplicated(subset=["cmrcl_time"], keep="first")
    return df[~dup].reset_index(drop=True)


WEEKDAY_LABELS_KR = ["월", "화", "수", "목", "금", "토", "일"]


@st.cache_data(ttl=1800)  # 30분 배치 주기와 맞춤 — 이보다 자주 새로 긁을 이유가 없다
def load_full_population_history(spot):
    """market_context 전체 누적분(페이지네이션)을 가져온다. T25 분석 스크립트와 동일한 방식."""
    rows = []
    start = 0
    page = 1000
    while True:
        res = (
            client.table("market_context")
            .select("collected_at,population_min,population_max")
            .eq("spot", spot)
            .order("collected_at")
            .range(start, start + page - 1)
            .execute()
        )
        chunk = res.data or []
        rows.extend(chunk)
        if len(chunk) < page:
            break
        start += page
    return pd.DataFrame(rows)


def render_weekday_heatmap(spot, color):
    """요일×시간대 평균 추정 인구 히트맵. 중간분석보고서(T25)에도 쓰는 것과 같은 집계라
    대표님이 대시보드에서 바로 '언제 붐비는지'를 확인할 수 있게 한다."""
    df = load_full_population_history(spot)
    if df.empty:
        st.markdown('<div class="bt-note">누적 데이터가 아직 부족합니다.</div>', unsafe_allow_html=True)
        return

    df["collected_kst"] = pd.to_datetime(df["collected_at"], utc=True).dt.tz_convert("Asia/Seoul")
    df["mid"] = (df["population_min"] + df["population_max"]) / 2
    df["weekday"] = df["collected_kst"].dt.weekday
    df["hour"] = df["collected_kst"].dt.hour

    pivot = (
        df.pivot_table(index="weekday", columns="hour", values="mid", aggfunc="mean")
        .reindex(index=range(7), columns=range(24))
    )
    span_days = (df["collected_kst"].max() - df["collected_kst"].min()).days + 1

    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=[f"{h}시" for h in range(24)],
        y=WEEKDAY_LABELS_KR,
        colorscale=[[0, SURFACE], [1, color]],  # 단일 색상 시퀀셜 — 값이 클수록 진하게
        hovertemplate="%{y}요일 %{x}<br>평균 추정 인구 %{z:,.0f}명<extra></extra>",
        colorbar=dict(title=dict(text="인구", font=dict(color=INK_MUTED)), tickfont=dict(color=INK_MUTED)),
        xgap=2, ygap=2,
    ))
    style_layout(fig, height=260)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key=f"heatmap_{spot}")

    missing_days = [WEEKDAY_LABELS_KR[d] for d in range(7) if pivot.loc[d].isna().all()]
    caption = f"누적 {span_days}일치 평균"
    if missing_days:
        caption += f" · 아직 데이터 없는 요일: {', '.join(missing_days)}"
    st.markdown(f'<div class="bt-caption" style="margin-top:0.4rem;">{caption}</div>', unsafe_allow_html=True)


@st.cache_data(ttl=3600)
def load_upcoming_events(limit=20):
    today = date.today().isoformat()
    res = (
        client.table("events")
        .select("*")
        .gte("end_date", today)
        .order("start_date")
        .limit(limit)
        .execute()
    )
    return pd.DataFrame(res.data)


def render_events_list():
    """반경 3km·향후 30일 행사(T10, V9+V10 통합) 중 아직 끝나지 않은 것만 날짜순으로."""
    events = load_upcoming_events()
    if events.empty:
        st.markdown('<div class="bt-note">예정된 행사가 없습니다.</div>', unsafe_allow_html=True)
        return

    # 각 행을 한 줄짜리 HTML로 만든다 — 들여쓴 여러 줄 문자열을 그대로 이어 붙이면
    # 중간에 빈 줄이 끼면서 마크다운이 그 지점에서 raw-HTML 블록을 끝내버리고,
    # 이후 들여쓴 줄들을 코드블록(리터럴 텍스트)으로 잘못 해석하는 문제가 있었다.
    row_parts = []
    for _, ev in events.iterrows():
        is_free = ev.get("is_free")
        if is_free is True:
            tag_html = '<span class="bt-pill" style="background:#22C55E">무료</span>'
        elif is_free is False:
            tag_html = f'<span class="bt-pill" style="background:{INK_FAINT}">유료</span>'
        else:
            tag_html = ""
        dist = ev.get("distance_m")
        dist_html = f" · {int(dist):,}m" if pd.notna(dist) else ""
        date_range = ev.get("start_date", "")
        if ev.get("end_date") and ev.get("end_date") != ev.get("start_date"):
            date_range += f" ~ {ev['end_date']}"

        row_parts.append(
            f'<div style="display:flex;justify-content:space-between;align-items:center;gap:1rem;'
            f'padding:0.75rem 0;border-bottom:1px solid {LINE};">'
            f'<div style="min-width:0;">'
            f'<div style="font-weight:600;color:{INK};font-size:0.9rem;">{ev.get("title", "")}</div>'
            f'<div style="color:{INK_MUTED};font-size:0.78rem;">{ev.get("place") or "장소 미상"}{dist_html}</div>'
            f'</div>'
            f'<div style="text-align:right;flex:none;">'
            f'<div class="mono" style="font-size:0.78rem;color:{INK_MUTED};">{date_range}</div>'
            f'{tag_html}'
            f'</div>'
            f'</div>'
        )

    st.markdown(f'<div class="bt-card">{"".join(row_parts)}</div>', unsafe_allow_html=True)


# ── 헤더 ──────────────────────────────────────────────────
st.markdown('<div class="bt-crumb">바틀링 AI PM · 상권 지표</div>', unsafe_allow_html=True)
st.markdown('<div class="bt-title">상권 대시보드</div>', unsafe_allow_html=True)

insight = build_insight()
if insight:
    st.markdown(f"""
    <div class="bt-insight">
      <span class="bt-insight-icon">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>
      </span>
      <span>{insight}</span>
    </div>
    """, unsafe_allow_html=True)

# ── 0. 협업 후보 지도 ────────────────────────────────────────
st.markdown('<div class="bt-section-title">협업 후보 지도</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="bt-section-sub">반경 1km 내 제과·베이커리·카페 — T15(추천 엔진) 전까지는 거리순으로만 표시</div>',
    unsafe_allow_html=True,
)
render_candidate_map()

# ── 1. 현재 혼잡도 · 추정 인구 ──────────────────────────────
st.markdown('<div class="bt-section-title">현재 혼잡도 · 추정 인구</div>', unsafe_allow_html=True)
st.markdown('<div class="bt-section-sub">30분 주기로 수집되는 실시간 도시데이터 기준</div>', unsafe_allow_html=True)

cols = st.columns(2)
for col, spot in zip(cols, SPOTS):
    with col:
        row = load_latest(spot["name"])
        if not row:
            st.markdown(f'<div class="bt-card">{spot["name"]} 데이터 없음</div>', unsafe_allow_html=True)
            continue

        level = row.get("congestion_level") or "데이터 없음"
        pill_color = CONGEST_COLOR.get(level, INK_FAINT)
        frac = CONGEST_FRAC.get(level, 0)
        pmin, pmax = row.get("population_min"), row.get("population_max")
        pop_text = f"{pmin:,} ~ {pmax:,}명" if pmin is not None else "데이터 없음"
        msg = row.get("congestion_msg") or ""
        collected = row.get("collected_at", "")

        hist = load_history(spot["name"], days=1)
        change_pct = None
        if not hist.empty:
            hist["mid"] = (hist["population_min"] + hist["population_max"]) / 2
            hist["collected_at"] = pd.to_datetime(hist["collected_at"], utc=True)
            earliest = hist["collected_at"].iloc[0]
            now_utc = pd.Timestamp.now(tz="UTC")
            # 창(window)의 첫 값이 24시간 전에 충분히 가까울 때만 "전일 대비"로 신뢰한다.
            if (now_utc - earliest) >= pd.Timedelta(hours=20) and pmin is not None:
                prev_mid = hist["mid"].iloc[0]
                current_mid = (pmin + pmax) / 2
                if prev_mid:
                    change_pct = (current_mid - prev_mid) / prev_mid * 100

        dot_color, rel_label, is_stale = freshness_status(collected)
        stale_html = (
            '<div class="bt-stale-warn">데이터 수집이 지연되고 있어요 — 크론 작업 상태 확인 필요</div>'
            if is_stale else ""
        )

        st.markdown(f"""
        <div class="bt-card">
          <div class="bt-card-head">
            <span class="bt-spot-name">{spot['name']}</span>
            <span class="bt-pill" style="background:{pill_color}">{level}</span>
          </div>
          <div class="bt-stat-label">추정 인구</div>
          <div class="bt-stat-value">{pop_text}</div>
          <div class="bt-change-row">{format_change_badge(change_pct)}</div>
          <div class="bt-track"><div class="bt-track-fill" style="width:{frac*100}%; background:{pill_color}"></div></div>
          <div class="bt-caption">{msg}</div>
          <div class="bt-caption">{weather_line(row)}</div>
          <div class="bt-timestamp" title="기준 시각 {collected}" style="--bt-live-color:{dot_color}"><span class="bt-live-dot"></span>{rel_label}</div>
          {stale_html}
        </div>
        """, unsafe_allow_html=True)

        if not hist.empty:
            st.plotly_chart(
                sparkline(hist["mid"], spot["color"]),
                use_container_width=True,
                config={"displayModeBar": False},
                key=f"spark_{spot['name']}",
            )

# ── 2. 12시간 예측 ──────────────────────────────────────────
st.markdown('<div class="bt-section-title">12시간 예측 · 추정 인구</div>', unsafe_allow_html=True)

st.markdown('<div class="bt-card">', unsafe_allow_html=True)
fig = go.Figure()
has_forecast = False
for spot in SPOTS:
    row = load_latest(spot["name"])
    if not row or not row.get("forecast_12h"):
        continue
    fc = pd.DataFrame(row["forecast_12h"])
    if fc.empty:
        continue
    has_forecast = True
    fc["mid"] = (fc["min"] + fc["max"]) / 2
    fc["time_label"] = pd.to_datetime(fc["time"]).dt.strftime("%H:%M")

    fig.add_trace(go.Scatter(
        x=fc["time_label"],
        y=fc["mid"],
        mode="lines+markers",
        name=spot["name"],
        line=dict(width=2.5, color=spot["color"], shape="spline", smoothing=0.3),
        marker=dict(size=7, color=spot["color"], line=dict(width=2, color=SURFACE)),
        customdata=fc[["min", "max", "level"]],
        hovertemplate=(
            "<b>%{x}</b><br>" + spot["name"] + "<br>"
            "예상 인구 %{customdata[0]:,}~%{customdata[1]:,}명<br>"
            "혼잡도 %{customdata[2]}<extra></extra>"
        ),
    ))

if has_forecast:
    style_layout(
        fig,
        yaxis_title="추정 인구 (명)",
        legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1, font=dict(color=INK)),
        height=340,
    )
    fig.update_yaxes(tickformat=",d", separatethousands=True)  # "10k" 대신 "10,000" — 카드 숫자·호버와 표기 통일
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
else:
    st.markdown('<div class="bt-note">12시간 예측 데이터가 아직 없습니다.</div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# ── 2b. 요일×시간대 인구 히트맵 ───────────────────────────────
st.markdown('<div class="bt-section-title">요일×시간대 인구 패턴</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="bt-section-sub">누적 데이터 기준 평균 — 중간분석보고서(T25)와 동일한 집계</div>',
    unsafe_allow_html=True,
)
heat_cols = st.columns(2)
for col, spot in zip(heat_cols, SPOTS):
    with col:
        st.markdown(f'<div class="bt-spot-name" style="margin-bottom:0.5rem;">{spot["name"]}</div>', unsafe_allow_html=True)
        st.markdown('<div class="bt-card">', unsafe_allow_html=True)
        render_weekday_heatmap(spot["name"], spot["color"])
        st.markdown('</div>', unsafe_allow_html=True)

# ── 3. 음식업 결제 추세 (뚝섬역 기준) ────────────────────────
st.markdown('<div class="bt-section-title">음식업 결제 추세</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="bt-section-sub">뚝섬역 기준 — 한강공원은 상권(결제) 데이터가 존재하지 않아 대리 지표로 사용</div>',
    unsafe_allow_html=True,
)

hist = load_history("뚝섬역", dedup_cmrcl=True)
hist = hist.dropna(subset=["pay_amt_min", "pay_amt_max"]) if not hist.empty else hist

st.markdown('<div class="bt-card">', unsafe_allow_html=True)
if hist.empty:
    st.markdown('<div class="bt-note">결제 데이터가 아직 충분하지 않습니다.</div>', unsafe_allow_html=True)
else:
    hist["collected_at"] = pd.to_datetime(hist["collected_at"])
    # 원 단위 그대로 쓰면 축 눈금이 "4M"처럼 자동 축약돼 카드의 콤마 표기와 어긋난다.
    # 만원 단위로 환산해 콤마 표기를 그대로 유지한다.
    hist["avg_amt_10k"] = (hist["pay_amt_min"] + hist["pay_amt_max"]) / 2 / 10000

    trend_fig = go.Figure()
    trend_fig.add_trace(go.Scatter(
        x=hist["collected_at"],
        y=hist["avg_amt_10k"],
        mode="lines",
        line=dict(width=2, color=ACCENT_STATION),
        fill="tozeroy",
        fillcolor="rgba(245,158,11,0.10)",
        name="뚝섬역 결제 추정액",
        hovertemplate="<b>%{x|%m/%d %H:%M}</b><br>추정 결제액 %{y:,.0f}만원<extra></extra>",
    ))
    style_layout(trend_fig, yaxis_title="추정 결제액 (만원)", showlegend=False, height=300)
    trend_fig.update_yaxes(tickformat=",d", separatethousands=True)
    st.plotly_chart(trend_fig, use_container_width=True, config={"displayModeBar": False})
st.markdown('</div>', unsafe_allow_html=True)

latest = load_latest("뚝섬역")
food_pay = latest.get("food_pay") if latest else None
if food_pay:
    st.markdown('<div class="bt-section-title" style="margin-top:1.1rem;">현재 업종별 결제 현황</div>', unsafe_allow_html=True)
    st.markdown('<div class="bt-card">', unsafe_allow_html=True)

    fp_df = pd.DataFrame([
        {"업종": k, "결제건수": v.get("count"), "혼잡도": v.get("level")}
        for k, v in food_pay.items()
    ]).sort_values("결제건수", ascending=True)

    bar_fig = go.Figure(go.Bar(
        x=fp_df["결제건수"],
        y=fp_df["업종"],
        orientation="h",
        marker=dict(color=ACCENT_STATION, cornerradius=6),
        hovertemplate="<b>%{y}</b><br>결제건수 %{x}건<extra></extra>",
    ))
    style_layout(bar_fig, xaxis_title="결제건수", height=200)
    bar_fig.update_xaxes(tickformat=",d", separatethousands=True)
    st.plotly_chart(bar_fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown('</div>', unsafe_allow_html=True)

# ── 4. 인근 행사 ─────────────────────────────────────────────
st.markdown('<div class="bt-section-title" style="margin-top:1.1rem;">인근 행사</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="bt-section-sub">반경 3km · 향후 30일 (서울시 문화행사 + 광진구청 게시판, T10)</div>',
    unsafe_allow_html=True,
)
render_events_list()
