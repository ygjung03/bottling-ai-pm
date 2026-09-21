"""
바틀링 AI PM — 진입점

실행: streamlit run app/main.py

"""
import _path  # noqa: F401  (프로젝트 루트를 sys.path 에 추가)
import streamlit as st

from app.auth import is_owner, login_form
from app.theme import BASE_CSS, render_topnav

st.set_page_config(page_title="바틀링 AI PM", page_icon="🍺",
                   layout="wide", initial_sidebar_state="collapsed")

# 홈 화면 전용 CSS — 히어로/미리보기 카드/기능 카드 그리드/로그인 화면.
# 공통 크롬(배경·사이드바 숨김·상단 내비 바 스타일)은 app/theme.BASE_CSS에 있다.
HOME_CSS = """
<style>
.block-container {
    padding-bottom: 3rem;
    max-width: 1180px;
}

/* 히어로 — 중앙 정렬 1단 구성 */
.hero {
    text-align: center;
    max-width: 780px;
    margin: 0 auto;
}
.hero-title {
    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 3.6rem;
    font-weight: 900;
    line-height: 1.2;
    letter-spacing: -0.025em;
    color: var(--ink);
    margin: 0 0 1.2rem 0;
    text-align: center;
}
.hero-sub {
    font-size: 1.1rem;
    color: var(--ink-soft);
    line-height: 1.6;
    margin: 0 auto 2.2rem auto;
    max-width: 32rem;
}

/* CTA 버튼 — 검정 채움 / 흰 아웃라인, 색은 안 쓴다 */
.st-key-hero_primary div[data-testid="stPageLink"] a,
.st-key-hero_secondary div[data-testid="stPageLink"] a {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.4rem;
    padding: 0.8rem 1.6rem;
    border-radius: 10px;
    font-weight: 600;
    font-size: 0.95rem;
    width: 100%;
    transition: transform 0.12s ease, box-shadow 0.12s ease, background 0.12s ease;
}
.st-key-hero_primary div[data-testid="stPageLink"] a {
    background: var(--ink);
    border: 1px solid var(--ink);
}
.st-key-hero_primary div[data-testid="stPageLink"] a p { color: #fff !important; }
.st-key-hero_primary div[data-testid="stPageLink"] a:hover {
    background: #2A2D34;
    transform: translateY(-1px);
    box-shadow: 0 8px 20px rgba(15,17,21,0.22);
}
.st-key-hero_secondary div[data-testid="stPageLink"] a {
    background: #fff;
    border: 1px solid var(--line);
}
.st-key-hero_secondary div[data-testid="stPageLink"] a p { color: var(--ink) !important; }
.st-key-hero_secondary div[data-testid="stPageLink"] a:hover {
    background: #F5F5F6;
    border-color: #D8D8DC;
}
/* Streamlit이 링크 라벨(<p>)에 자체 텍스트색을 직접 지정해서 부모 <a>의
   color 상속만으로는 안 먹는다 — 항상 p 를 따로 짚어줘야 한다. */
div[data-testid="stPageLink"] a p { font-weight: 600 !important; }
/* Streamlit 라벨을 감싸는 span에 자체적으로 overflow:hidden + ellipsis가
   걸려 있어서, 버튼이 좁으면 글자가 잘려 보인다 (예: "파트너 추천 시작"
   → "파트너 추"). 잘림 방지용으로 강제 해제. */
.st-key-hero_primary div[data-testid="stPageLink"] a span,
.st-key-hero_secondary div[data-testid="stPageLink"] a span {
    overflow: visible !important;
    text-overflow: clip !important;
    width: auto !important;
    flex-shrink: 0 !important;
}

/* 미리보기 카드 — 화려한 배경 없이 카드 하나만 깔끔하게 */
.preview-wrap { max-width: 620px; margin: 2.6rem auto 0 auto; }
.preview-card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 18px;
    padding: 1.5rem 1.7rem;
    box-shadow: 0 16px 40px -24px rgba(15,17,21,0.18);
    text-align: left;
}
.preview-card .ph-head {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 1rem;
}
.preview-card .ph-title { font-weight: 700; font-size: 0.95rem; color: var(--ink); }
.preview-card .ph-badge {
    font-size: 0.72rem; font-weight: 600; color: var(--accent);
    background: var(--accent-tint); padding: 0.2rem 0.55rem; border-radius: 999px;
}
.ph-row {
    display: flex; align-items: center; gap: 0.7rem;
    padding: 0.55rem 0; border-bottom: 1px solid var(--line);
}
.ph-row:last-child { border-bottom: none; }
.ph-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.ph-name {
    font-size: 0.86rem; color: var(--ink); font-weight: 600; flex: 1;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ph-bar-wrap { width: 100px; height: 6px; background: #F0F0F1; border-radius: 999px; overflow: hidden; flex-shrink: 0; }
.ph-bar { height: 100%; border-radius: 999px; }
.ph-score { font-size: 0.78rem; color: var(--ink-soft); width: 34px; text-align: right; flex-shrink: 0; }
.ph-empty {
    padding: 1.2rem 0.3rem; font-size: 0.85rem; color: var(--ink-soft);
    line-height: 1.6; text-align: center;
}
.ph-empty code { background: var(--paper); padding: 0.1rem 0.4rem; border-radius: 6px; font-size: 0.8rem; }

/* 신뢰 요소 3줄 */
.trust-row {
    display: flex; justify-content: center; gap: 1.8rem; flex-wrap: wrap;
    margin: 1.4rem auto 0 auto; max-width: 640px;
}
.trust-item {
    display: flex; align-items: center; gap: 0.4rem;
    font-size: 0.82rem; color: var(--ink-soft); font-weight: 500;
}
.trust-item svg { width: 15px; height: 15px; flex-shrink: 0; color: var(--ink-soft); }

/* 기능 카드 그리드 */
.section-label {
    font-size: 0.8rem; font-weight: 700; color: var(--ink-soft);
    letter-spacing: 0.04em; text-transform: uppercase; margin-bottom: 0.4rem;
    text-align: center;
}
.section-title {
    font-size: 1.5rem; font-weight: 800; color: var(--ink);
    margin-bottom: 2rem; text-align: center;
}
/* 주의: ":has(.card-marker)" 처럼 흔한 클래스로 걸면 그 마커를 포함하는
   "모든 조상" 래퍼에 다 걸려버린다 — 페이지 최상단 래퍼까지 걸려서
   화면 전체를 둥근 테두리로 감싸는 버그가 있었다. 카드별 고유 key로
   "바로 위" 래퍼만 짚도록 direct-child(>) + 속성 부분일치로 한정한다. */
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[class*="st-key-feature_card_"]) {
    border-radius: 14px !important;
    border: 1px solid var(--line) !important;
    transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
    background: var(--card);
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[class*="st-key-feature_card_"]):hover {
    transform: translateY(-3px);
    box-shadow: 0 16px 32px -18px rgba(15,17,21,0.22);
    border-color: #C7C7CC !important;
}
.card-icon {
    width: 40px; height: 40px; border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    margin-bottom: 0.9rem;
    background: #F1F1F3;
    color: var(--ink);
}
.card-icon svg { width: 19px; height: 19px; }
.card-title { font-weight: 700; font-size: 1.02rem; color: var(--ink); margin-bottom: 0.35rem; }
.card-desc { font-size: 0.86rem; color: var(--ink-soft); line-height: 1.55; margin-bottom: 0.9rem; }
.card-link div[data-testid="stPageLink"] a {
    background: var(--paper);
    padding: 0.35rem 0.85rem;
    border-radius: 999px;
    border: 1px solid var(--line);
    font-size: 0.8rem !important;
}
.card-link div[data-testid="stPageLink"] a:hover {
    background: var(--ink);
    border-color: var(--ink);
}
.card-link div[data-testid="stPageLink"] a:hover p { color: #fff !important; }

/* 로그인 화면 */
.login-title { font-size: 2.1rem; font-weight: 800; color: var(--ink); margin: 0.6rem 0 0.2rem 0; text-align: center; }
</style>
"""
st.markdown(BASE_CSS, unsafe_allow_html=True)
st.markdown(HOME_CSS, unsafe_allow_html=True)


@st.cache_data(ttl=300)
def load_home_preview() -> dict | None:
    """추천 후보 미리보기용 — nearby_stores 상위 3곳 + 전체 건수.
    T15를 안 돌렸거나(score 전부 NULL) DB 연결이 안 되면 None."""
    try:
        from db.client import get_client
        client = get_client()
        total = client.table("nearby_stores").select("store_id", count="exact").execute().count or 0
        top = (
            client.table("nearby_stores")
            .select("name,score")
            .not_.is_("score", "null")
            .order("score", desc=True)
            .limit(3)
            .execute()
            .data
        )
        if not top:
            return None
        return {"total": total, "top": top}
    except Exception:
        return None


def render_preview_card() -> None:
    stats = load_home_preview()
    # 색을 안 쓰기로 했으니 순위는 검정~회색 톤 단계로만 구분한다.
    palette = ["#0F1115", "#6B7280", "#B7B9BF"]
    if stats:
        rows_html = "".join(
            f'<div class="ph-row"><span class="ph-dot" style="background:{palette[i % 3]}"></span>'
            f'<span class="ph-name">{r["name"]}</span>'
            f'<span class="ph-bar-wrap"><span class="ph-bar" '
            f'style="width:{int(r["score"] * 100)}%;background:{palette[i % 3]}"></span></span>'
            f'<span class="ph-score">{r["score"]:.2f}</span></div>'
            for i, r in enumerate(stats["top"])
        )
        badge = f'{stats["total"]}건'
    else:
        rows_html = (
            '<div class="ph-empty">아직 점수 데이터가 없습니다.<br>'
            '<code>python -m recommender.run</code> 실행 후 채워집니다.</div>'
        )
        badge = "대기중"

    st.markdown(
        '<div class="preview-wrap">'
        f'<div class="preview-card"><div class="ph-head">'
        f'<span class="ph-title">추천 후보 · 반경 1km</span>'
        f'<span class="ph-badge">{badge}</span></div>{rows_html}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


_ICON_SVG = {
    "search": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
              'stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/>'
              '<line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    "edit": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/>'
            '<path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>',
    "chart": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/>'
             '<line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
    "gear": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/>'
            '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 '
            '1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 '
            '19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 '
            '.33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 '
            '0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 '
            '1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 '
            '1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 '
            '0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
    "refresh": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
               'stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/>'
               '<polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 '
               '14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>',
    "bolt": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
    "pin": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
           'stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>'
           '<circle cx="12" cy="10" r="3"/></svg>',
}


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
render_topnav()

st.markdown(
    '<div class="hero">'
    '<div class="hero-title">데이터로 완성하는<br>협업 기획</div>'
    '<div class="hero-sub">반경 1km 점포를 점수화해 협업 후보를 추천하고, '
    '메뉴·이벤트·홍보안을 한 번에 만듭니다.</div>'
    '</div>',
    unsafe_allow_html=True,
)

_, bmid, _ = st.columns([0.8, 2, 0.8])
with bmid:
    b1, b2 = st.columns(2, gap="small")
    with b1:
        with st.container(key="hero_primary"):
            st.page_link("pages/3_파트너_추천.py", label="파트너 추천")
    with b2:
        with st.container(key="hero_secondary"):
            st.page_link("pages/2_기획안_생성.py", label="기획안 생성")

render_preview_card()

st.markdown(
    '<div class="trust-row">'
    f'<span class="trust-item">{_ICON_SVG["refresh"]}데이터는 5분마다 새로고침</span>'
    f'<span class="trust-item">{_ICON_SVG["bolt"]}기획안은 약 30초면 완성</span>'
    f'<span class="trust-item">{_ICON_SVG["pin"]}반경 1km 후보를 자동 점수화</span>'
    '</div>',
    unsafe_allow_html=True,
)

st.write("")
st.write("")

st.markdown('<div class="section-label">둘러보기</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">4개 화면으로 협업 기획을 끝냅니다</div>', unsafe_allow_html=True)

cards = [
    ("search", "파트너 추천", "반경 1km 점포를 점수화해 협업 후보를 제시합니다.", "pages/3_파트너_추천.py"),
    ("edit", "기획안 생성", "메뉴·이벤트·홍보안을 한 번에 만듭니다. 약 30초 소요.", "pages/2_기획안_생성.py"),
    ("chart", "상권 대시보드", "뚝섬 실시간 인구·결제 현황을 봅니다.", "pages/4_상권_대시보드.py"),
    ("gear", "관리", "맥주 라인업, 프롬프트, 제약조건을 수정합니다.", "pages/9_관리.py"),
]
cols = st.columns(4, gap="medium")
for i, (col, (icon_key, title, desc, target)) in enumerate(zip(cols, cards)):
    with col:
        with st.container(border=True, key=f"feature_card_{i}"):
            st.markdown(f'<div class="card-icon">{_ICON_SVG[icon_key]}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="card-title">{title}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="card-desc">{desc}</div>', unsafe_allow_html=True)
            st.markdown('<div class="card-link">', unsafe_allow_html=True)
            st.page_link(target, label="바로가기")
            st.markdown('</div>', unsafe_allow_html=True)

st.write("")
st.divider()
st.caption("협력사 입력 폼은 초대 코드로 접근합니다. "
           "파트너 추천 화면에서 링크를 만들 수 있습니다.")