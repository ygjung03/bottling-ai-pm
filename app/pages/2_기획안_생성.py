"""
기획안 생성 — 핵심 화면

체인 4단계를 순차 실행한다. 실측 약 17초이므로 동기 방식으로 충분하다.
다만 무반응 구간이 길게 느껴지고 어느 단계에서 실패했는지 보여야 하므로
단계별 진행 표시는 유지한다. (명세서 4-2, 6-2-3)
"""
import _path  # noqa: F401  (프로젝트 루트를 sys.path 에 추가)
import streamlit as st

from app.auth import require_owner

st.set_page_config(page_title="기획안 생성", page_icon="📝", layout="wide")
require_owner()

st.title("기획안 생성")

c1, c2, c3 = st.columns([2, 2, 1])
with c1:
    st.selectbox("협력사", ["(선택)"], disabled=True)
with c2:
    st.date_input("실행 희망일")
with c3:
    st.write("")
    st.button("기획안 생성", type="primary", use_container_width=True,
              disabled=True)

st.divider()
st.info("협력사를 선택하면 기획안을 생성할 수 있습니다.")

# TODO(T22): 생성 실행 + 진행 표시 + 결과 탭
st.caption("T22에서 구현 예정 — 진행 표시, 3안 탭, 채택/폐기")
