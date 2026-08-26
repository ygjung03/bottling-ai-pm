"""
바틀링 AI PM — 진입점

실행: streamlit run app/main.py
"""
import _path  # noqa: F401  (프로젝트 루트를 sys.path 에 추가)
import streamlit as st

from app.auth import is_owner, login_form, logout

st.set_page_config(page_title="바틀링 AI PM", page_icon="🍺",
                   layout="wide", initial_sidebar_state="expanded")

if not is_owner():
    # 로그인 전에는 사이드바의 페이지 목록을 감춘다
    st.markdown("<style>[data-testid='stSidebarNav']{display:none}</style>",
                unsafe_allow_html=True)
    st.title("바틀링 AI PM")
    st.caption("소상공인 협업 기획 자동화")
    st.write("")
    login_form()
    st.divider()
    st.caption("협력사 정보 입력은 전달받으신 링크로 접속해 주세요.")
    st.stop()

# ── 로그인 후 ──
st.title("바틀링 AI PM")
st.caption("소상공인 협업 기획 자동화")

with st.sidebar:
    st.divider()
    if st.button("로그아웃", use_container_width=True):
        logout()

st.write("")
c1, c2 = st.columns(2)

with c1:
    st.subheader("협업 기획")
    st.page_link("pages/3_파트너_추천.py", label="파트너 추천", icon="🔍")
    st.caption("반경 1km 점포를 점수화해 협업 후보를 제시합니다.")
    st.write("")
    st.page_link("pages/2_기획안_생성.py", label="기획안 생성", icon="📝")
    st.caption("메뉴·이벤트·홍보안을 한 번에 만듭니다. 약 17초 소요.")

with c2:
    st.subheader("상권")
    st.page_link("pages/4_상권_대시보드.py", label="상권 대시보드", icon="📊")
    st.caption("뚝섬 실시간 인구·결제 현황을 봅니다.")
    st.write("")
    st.page_link("pages/9_관리.py", label="관리", icon="⚙️")
    st.caption("맥주 라인업, 프롬프트, 제약조건을 수정합니다.")

st.divider()
st.caption("협력사 입력 폼은 초대 코드로 접근합니다. "
           "파트너 추천 화면에서 링크를 만들 수 있습니다.")
