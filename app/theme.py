"""
공통 UI — 상단 내비게이션 + 색/폰트 테마

사용법 (각 페이지 최상단, require_owner() 바로 다음 — 그 페이지 자체
CSS/내용보다 먼저 호출해야 상단 바가 맨 위에 온다):

    from app.auth import require_owner
    from app.theme import apply_chrome

    st.set_page_config(...)
    require_owner()
    apply_chrome()
    # 이 아래에 페이지 고유 내용
"""
import sys
from pathlib import Path

import streamlit as st

from app.auth import logout

BASE_CSS = """
<style>
/* 헤드라인 등에 쓰는 폰트 — Pretendard (무료, 한글 지원 좋은 굵은 산세리프).
   각 페이지가 자기 폰트를 따로 쓰고 있으면(예: 상권 대시보드의 Noto Sans KR)
   그 페이지 CSS가 나중에 로드되며 그대로 이긴다 — 강제로 덮어쓰지 않는다. */
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');

:root {
    --ink: #0F1115;
    --ink-soft: #6B7280;
    --paper: #FAFAFA;
    --card: #FFFFFF;
    --line: #E7E7EA;
    --accent: #2F6FE0;
    --accent-tint: #EAF2FE;
}

[data-testid="stMain"], [data-testid="stAppViewContainer"] {
    background: var(--paper) !important;
}
[data-testid="stDecoration"] { display: none; }
[data-testid="stHeader"] { background: transparent; }
/* 내비게이션을 상단 바로 옮겼기 때문에 기본 사이드바는 모든 페이지에서 뺀다 */
[data-testid="stSidebar"],
[data-testid="stSidebarNav"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"] { display: none !important; }
.block-container { padding-top: 1.6rem; }

/* 상단 내비게이션 바 */
.st-key-topnav {
    padding-bottom: 0.9rem;
    border-bottom: 1px solid var(--line);
    margin-bottom: 2.2rem;
}
.st-key-topnav_brand div[data-testid="stPageLink"] a {
    background: transparent !important;
    border: none !important;
    padding: 0.3rem 0 !important;
    justify-content: flex-start !important;
}
.st-key-topnav_brand div[data-testid="stPageLink"] a p {
    font-weight: 800 !important;
    font-size: 1.05rem !important;
    color: var(--ink) !important;
}
.st-key-topnav_links div[data-testid="stPageLink"] a {
    background: transparent !important;
    border: none !important;
    padding: 0.3rem 0.1rem !important;
    justify-content: center !important;
}
.st-key-topnav_links div[data-testid="stPageLink"] a p {
    font-weight: 500 !important;
    font-size: 0.88rem !important;
    color: var(--ink-soft) !important;
}
.st-key-topnav_links div[data-testid="stPageLink"] a:hover p {
    color: var(--ink) !important;
}
.st-key-topnav_logout button {
    background: transparent !important;
    border: 1px solid var(--line) !important;
    color: var(--ink-soft) !important;
    font-size: 0.84rem !important;
    font-weight: 500 !important;
    border-radius: 8px !important;
    padding: 0.35rem 0.9rem !important;
}
.st-key-topnav_logout button:hover {
    border-color: #C7C7CC !important;
    color: var(--ink) !important;
    background: var(--paper) !important;
}
/* 좁은 내비 버튼에서도 텍스트 잘림 방지 — 히어로 버튼에서 겪은 문제와 동일
   (Streamlit이 라벨 <span>에 자체 overflow:hidden + ellipsis를 건다) */
.st-key-topnav div[data-testid="stPageLink"] a span {
    overflow: visible !important;
    text-overflow: clip !important;
    width: auto !important;
    flex-shrink: 0 !important;
}
div[data-testid="stPageLink"] a { text-decoration: none !important; }
</style>
"""


def _entry_page() -> str:
    """
    실행된 진입점 파일명(main.py, 또는 가안 비교용으로 main_2.py 등으로
    저장했다면 그 이름)을 돌려준다.

    st.page_link는 "지금 이 파일" 기준이 아니라 항상 "진입점 파일" 기준
    상대경로를 요구한다. 페이지 파일 자신의 __file__을 쓰면 여기(예:
    3_파트너_추천.py)에서는 틀린 값이 나온다. Streamlit은 페이지를
    exec()로 돌릴 뿐 프로세스를 새로 띄우지 않으므로, 최초 실행 인자인
    sys.argv[0]은 어느 페이지에서 봐도 항상 진입점 그대로 남아 있다.
    """
    return Path(sys.argv[0]).name


def render_topnav() -> None:
    entry = _entry_page()
    with st.container(key="topnav"):
        nav_brand, nav_links, nav_logout = st.columns(
            [1.8, 4.2, 0.9], vertical_alignment="center"
        )
        with nav_brand:
            with st.container(key="topnav_brand"):
                st.page_link(entry, label="바틀링 AI PM")
        with nav_links:
            with st.container(key="topnav_links"):
                l1, l2, l3, l4 = st.columns(4, gap="small")
                with l1:
                    st.page_link("pages/3_파트너_추천.py", label="파트너 추천")
                with l2:
                    st.page_link("pages/2_기획안_생성.py", label="기획안 생성")
                with l3:
                    st.page_link("pages/4_상권_대시보드.py", label="상권 대시보드")
                with l4:
                    st.page_link("pages/9_관리.py", label="관리")
        with nav_logout:
            with st.container(key="topnav_logout"):
                if st.button("로그아웃", use_container_width=True, key="topnav_logout_btn"):
                    logout()


def apply_chrome() -> None:
    """페이지 공통 크롬 적용 — CSS 주입 + 상단 내비 렌더링.

    require_owner() 통과한 다음, 그 페이지 고유 내용보다 먼저 호출한다.
    """
    st.markdown(BASE_CSS, unsafe_allow_html=True)
    render_topnav()