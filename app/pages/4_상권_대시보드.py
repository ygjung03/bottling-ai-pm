"""
상권 대시보드 — 8/31 2차 방문에서 보여줄 화면

완성도보다 "데이터가 실제로 쌓이고 있다"를 보이는 것이 목적이다.
대표님이 데이터 기반 제안을 신뢰하지 않는 상황에서(설계 결정 D6)
실시간 지표를 직접 보여주는 것이 가장 빠른 설득 수단이다.
"""
import _path  # noqa: F401  (프로젝트 루트를 sys.path 에 추가)
import streamlit as st

from app.auth import require_owner

st.set_page_config(page_title="상권 대시보드", page_icon="📊", layout="wide")
require_owner()

st.title("상권 대시보드")
st.caption("뚝섬한강공원 · 뚝섬역 실시간 현황")

c1, c2, c3, c4 = st.columns(4)
c1.metric("한강공원 혼잡도", "—")
c2.metric("뚝섬역 혼잡도", "—")
c3.metric("추정 인구", "—")
c4.metric("기온", "—")

st.divider()
st.subheader("12시간 예측")
st.info("수집 데이터를 불러와 표시합니다.")

st.subheader("음식업 결제 추세")
st.caption("뚝섬역 기준 · 중분류 4종")
st.info("수집 데이터를 불러와 표시합니다.")

# TODO(T24b): market_context 조회 + 차트
st.caption("T24b에서 구현 예정")
