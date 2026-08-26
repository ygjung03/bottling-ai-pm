"""
파트너 추천 — 두 경로 병행

대표님이 이미 협업할 가게를 정해둔 경우가 실제로는 더 많다.
추천 결과에서만 고르게 하면 시스템을 우회하게 되므로
직접 지정 경로를 같은 화면에 둔다. (명세서 4-3)
"""
import _path  # noqa: F401  (프로젝트 루트를 sys.path 에 추가)
import streamlit as st

from app.auth import require_owner

st.set_page_config(page_title="파트너 추천", page_icon="🔍", layout="wide")
require_owner()

st.title("파트너 추천")

tab_rec, tab_manual = st.tabs(["추천받기", "직접 지정"])

with tab_rec:
    c1, c2 = st.columns([1, 3])
    with c1:
        st.slider("반경 (m)", 200, 1000, 1000, step=100)
        st.multiselect("업종", ["기타 간이", "비알코올", "한식", "일식/중식/양식"])
    with c2:
        st.info("추천 엔진 구현 후 후보 목록이 표시됩니다.")
    st.caption("T24에서 구현 예정 — 스코어링 결과, 지도, 상세 패널")

with tab_manual:
    st.text_input("가게 이름 검색")
    st.caption("반경 밖이거나 목록에 없으면 직접 입력할 수 있습니다.")
    st.info("검색 결과가 없으면 상호·업종·주소를 직접 입력합니다.")
    st.caption("T24에서 구현 예정")

st.divider()
st.caption("협력사가 미등록이면 초대 링크를 발급해 전달합니다.")
