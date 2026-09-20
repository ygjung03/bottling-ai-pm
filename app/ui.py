"""
공통 화면 요소 — 사이드바와 페이지 머리.

시안 docs/ref/피그마_예시2.pdf 의 왼쪽 메뉴를 그대로 옮긴 것이다 (9/21).
Streamlit 기본 페이지 목록은 감추고, 메뉴 다섯 개를 NAV 순서로 그린다.

사용법
    from app.ui import sidebar, page_header
    sidebar("기획안 생성")                 # 페이지 맨 위 (require_owner 다음)
    page_header("기획안 생성", "설명 한 줄")
"""
import streamlit as st

# 시안 글자 그대로. 바꿀 때는 여기만 고친다.
BRAND_MARK = "P"
BRAND_NAME = "PlanGen AI"
USER_NAME = "소복소복"
USER_ROLE = "서울 AI 재단 청년팀"

# (이름, material 아이콘, 페이지 경로). 시안의 다섯 칸을 실제 페이지로 바꿨다 (9/21):
#   홈 → 맨 위에 추가 / 기획안 생성 → 그대로 / 보관함 자리 → 파트너 추천 /
#   데이터 분석 → 상권 대시보드 (그래프 아이콘 그대로) / 협력처 관리 → 뺌 /
#   관리 →  환경 설정 페이지 (아이콘·글자 그대로)
NAV = [
    ("홈", "home", "main.py"),
    ("기획안 생성", "description", "pages/2_기획안_생성.py"),
    ("파트너 추천", "handshake", "pages/3_파트너_추천.py"),
    ("상권 대시보드", "monitoring", "pages/4_상권_대시보드.py"),
    ("환경 설정", "settings", "pages/9_관리.py"),
]

_BG = "#0F172A"        # 사이드바 바탕
_ACTIVE = "#1E293B"    # 고른 메뉴 바탕
_MUTED = "#94A3B8"     # 안 고른 메뉴 글자
_LINE = "#1E293B"      # 아래 구분선

_CSS = f"""
<style>
[data-testid="stSidebarNav"] {{ display: none; }}
[data-testid="stSidebar"] {{ background: {_BG}; }}
[data-testid="stSidebar"] > div:first-child {{ padding-top: 8px; }}
[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] button,
[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] svg {{ color: {_MUTED}; }}
[data-testid="stSidebar"] hr {{ border-color: {_LINE}; margin: 12px 0; }}

/* 메뉴 한 줄. st.page_link 를 시안 모양으로 */
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] {{
  display: flex; align-items: center; gap: 12px;
  padding: 11px 16px; border-radius: 10px; margin: 2px 0;
  color: {_MUTED}; font-size: 0.95rem; font-weight: 500; text-decoration: none;
}}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] span,
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] p {{ color: inherit; font-weight: inherit; }}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover {{ background: {_ACTIVE}; color: #E2E8F0; }}
</style>
"""

_LOGO = f"""
<div style="display:flex; align-items:center; gap:12px; padding:16px 10px 22px">
  <div style="width:34px; height:34px; border-radius:9px; background:#2563EB; color:#fff;
              display:flex; align-items:center; justify-content:center;
              font-weight:800; font-size:1.15rem">{BRAND_MARK}</div>
  <div style="color:#fff; font-weight:800; font-size:1.15rem">{BRAND_NAME}</div>
</div>
"""

_USER = f"""
<div style="border-top:1px solid {_LINE}; margin-top:40px; padding:18px 8px 6px;
            display:flex; align-items:center; gap:14px">
  <div style="width:38px; height:38px; border-radius:50%; background:{_ACTIVE};
              border:1.5px solid #CBD5E1"></div>
  <div>
    <div style="color:#fff; font-weight:700; font-size:0.95rem">{USER_NAME}</div>
    <div style="color:{_MUTED}; font-size:0.8rem">{USER_ROLE}</div>
  </div>
</div>
"""


def sidebar(active: str) -> None:
    """시안의 왼쪽 메뉴. active 는 NAV 의 이름 중 하나."""
    # 고른 메뉴의 CSS 도 맨 위 style 한 덩이에 넣는다. 메뉴 사이에 style 요소를
    # 따로 끼우면 Streamlit 이 그 자리에도 간격을 줘서 버튼 위치가 밀린다 (9/21).
    idx = next((i for i, (name, _, _) in enumerate(NAV) if name == active), None)
    active_css = "" if idx is None else (
        f"<style>.st-key-nav_{idx} [data-testid='stPageLink-NavLink'] {{"
        f" background:{_ACTIVE}; color:#FFFFFF; font-weight:700; }}"
        f".st-key-nav_{idx} [data-testid='stPageLink-NavLink'] p,"
        f".st-key-nav_{idx} [data-testid='stPageLink-NavLink'] span {{"
        f" color:#FFFFFF; font-weight:700; }}</style>")
    with st.sidebar:
        st.markdown(_CSS + active_css, unsafe_allow_html=True)
        st.markdown(_LOGO, unsafe_allow_html=True)
        for i, (name, icon, page) in enumerate(NAV):
            # page_link 에는 class 를 못 준다. key 가 붙은 상자(st-key-nav_i)로
            # 감싸서 고른 메뉴만 CSS 로 칠한다.
            with st.container(key=f"nav_{i}"):
                st.page_link(page, label=name, icon=f":material/{icon}:",
                             use_container_width=True)
        st.markdown(_USER, unsafe_allow_html=True)


def page_header(title: str, subtitle: str) -> None:
    """시안의 페이지 머리 — 큰 제목과 회색 설명 한 줄."""
    st.markdown(
        f'<div style="font-size:1.9rem; font-weight:800; color:#0F172A; margin:4px 0 2px">'
        f'{title}</div>'
        f'<div style="color:#64748B; font-size:0.95rem; margin-bottom:22px">{subtitle}</div>',
        unsafe_allow_html=True)
