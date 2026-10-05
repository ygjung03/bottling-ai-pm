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

# 보관함 개수. 화면이 상단 바를 그리기 전에 넣어 둔다 — 상단 바는 협력사를
# 모르고, 그걸 아는 것은 화면이다.
SS_ARCHIVE_COUNT = "archive_count"

# 고른 협력사 id. 셀렉트박스 값("partner_pick")을 그대로 쓰지 못한다 — Streamlit 은
# 위젯이 그려지지 않은 실행에서 그 key 의 세션 값을 지운다. 보관함으로 갈라지거나
# 다른 화면으로 넘어가면 셀렉트박스가 안 그려져 값이 사라진다. 위젯 키가 아닌
# 곳에 복사해 둔다.
#
# 두 화면이 쓴다 — 파트너 추천이 고른 협력사를 여기 넣고, 기획안 생성이 그것을
# 셀렉트박스 기본값으로 읽는다. 그래서 공용인 여기에 둔다.
SS_PARTNER_ID = "partner_id_last"

# 보관함이 열렸는지는 주소의 질의 문자열에 둔다. 세션에 두면 다른 화면에 갔다
# 돌아왔을 때도 켜진 채로 남아, 「기획안 생성」을 눌렀는데 아무 변화가 없는것처럼 보인다.
#
# 다른 화면으로 이동하면 이 값은 떨어진다. **같은 화면은 다르다** (9/30 확인) —
# 보관함에서 「기획안 생성」을 누르면 값을 그대로 들고 가 보관함이 다시 그려지고,
# 눈에는 아무 일도 안 일어난 것으로 보인다. 그래서 그 항목만 버튼으로 둔다.
ARCHIVE_PARAM = "archive"

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
/* 보관함 안에서만 나오는 「기획안 생성」 버튼 — 옆 링크들과 같은 자리에 같은
   모양으로 서야 한다. 버튼은 테두리·최소 높이·여백 기본값이 링크와 달라 그냥
   두면 아래로 내려앉는다. all:unset 으로 버튼 상자를 통째로 풀고 링크(a)에
   준 값과 똑같이 다시 준다. */
/* 옆 링크들은 **칸 왼쪽**에 붙어 있다. 위 a 규칙의 justify-content:center 는
   효과가 없다 — a 가 글자 폭만큼만 차지해서 가운데로 몰 여백이 없다.
   브라우저에서 잰 값 (9/30):

     칸1  409.5 ~ 584.0   글자 411.1 ~ 478.7   ← 칸 왼쪽 + padding 만큼

   그래서 버튼도 왼쪽에 붙인다. 가운데로 두면 53px 오른쪽으로 밀린다. */
.st-key-topnav_plan,
.st-key-topnav_plan > div,
.st-key-topnav_plan div[data-testid="stVerticalBlock"] {
    margin: 0 !important;
    padding: 0 !important;
    gap: 0 !important;
}
.st-key-topnav_plan button {
    all: unset;
    display: flex !important;
    width: 100% !important;
    justify-content: flex-start !important;
    align-items: center !important;
    padding: 0.3rem 0.1rem !important;
    cursor: pointer !important;
    font-family: inherit !important;
}
.st-key-topnav_plan button div[data-testid="stMarkdownContainer"] {
    width: auto !important;
}
/* 누를 때 파란 바탕이 번지지 않게 — 링크에는 그런 상태가 없다 */
.st-key-topnav_plan button:hover,
.st-key-topnav_plan button:focus,
.st-key-topnav_plan button:focus-visible,
.st-key-topnav_plan button:active {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
    color: inherit !important;
}
.st-key-topnav_plan button p {
    margin: 0 !important;
    text-align: left !important;
    font-weight: 500 !important;
    font-size: 0.88rem !important;
    line-height: 1.4 !important;
    color: var(--ink-soft) !important;
}
.st-key-topnav_plan button:hover p { color: var(--ink) !important; }

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


def render_topnav(right: str = "") -> None:
    """
    상단 내비 바. right 가 오른쪽 끝 자리를 정한다 (9/30).

      "logout"    로그아웃          홈 (main.py) 에만
      "archive"   보관함            기획안 생성 화면에만
      ""          비운다            파트너 추천 · 상권 대시보드 · 관리

    한 자리를 화면마다 나눠 쓴다. 규칙은 「그 화면에 필요한 것 하나」다.

    로그아웃을 모든 화면에 두면 정작 그 화면의 동작을 넣을 자리가 없어진다.
    세션을 끝내는 동작이라 나가는 곳인 홈에 두는 편이 자연스럽고, 다른 화면에서
    찾더라도 홈으로 접근 후 로그아웃 버튼 누르는데까지 두번 클릭이면 된다. 

    보관함은 기획안 생성과 한 몸이라 다른 화면에서는 갈 일이 없다. 그래서 나머지 세
    화면은 이 자리를 비운다.

    보관함 개수는 화면이 넘긴다. 협력사마다 다른 값이라 여기서 셀 수 없다.
    """
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
                    # 보관함 안에서는 링크가 안 듣는다 (같은 화면이라 주소의
                    # 표시를 그대로 들고 간다). 버튼으로 두고 직접 지운다.
                    if ARCHIVE_PARAM in st.query_params:
                        # 컨테이너로 감싸야 한다. 이 버전에서 st-key- 클래스는
                        # st.container(key=) 에만 붙고 위젯 key 로는 안 붙는다.
                        with st.container(key="topnav_plan"):
                            if st.button("기획안 생성", key="topnav_plan_btn",
                                         use_container_width=True):
                                del st.query_params[ARCHIVE_PARAM]
                                st.rerun()
                    else:
                        st.page_link("pages/2_기획안_생성.py", label="기획안 생성")
                with l3:
                    st.page_link("pages/4_상권_대시보드.py", label="상권 대시보드")
                with l4:
                    st.page_link("pages/9_관리.py", label="관리")
        with nav_logout:
            if right == "logout":
                with st.container(key="topnav_logout"):
                    if st.button("로그아웃", use_container_width=True,
                                 key="topnav_logout_btn"):
                        logout()
            elif right == "archive":
                with st.container(key="topnav_logout"):
                    n = st.session_state.get(SS_ARCHIVE_COUNT) or 0
                    label = f"보관함  {n}" if n else "보관함"
                    if st.button(label, use_container_width=True,
                                 key="topnav_archive_btn",
                                 icon=":material/inventory_2:"):
                        st.query_params[ARCHIVE_PARAM] = "1"
                        st.rerun()


def apply_chrome(right: str = "") -> None:
    """페이지 공통 크롬 적용 — CSS 주입 + 상단 내비 렌더링.

    require_owner() 통과한 다음, 그 페이지 고유 내용보다 먼저 호출한다.
    right 는 render_topnav() 의 것과 같다.
    """
    st.markdown(BASE_CSS, unsafe_allow_html=True)
    render_topnav(right)