"""
관리 — 개발팀 및 이관 대비

프롬프트를 코드에서 분리해 비개발자가 수정할 수 있게 한다. (설계 결정 D7)
사업 종료 후 대표님이 직접 유지하는 것은 비현실적이나,
최소한 프롬프트와 제약조건은 화면에서 고칠 수 있어야 한다.
"""
import _path  # noqa: F401  (프로젝트 루트를 sys.path 에 추가)
import streamlit as st

from app.auth import require_owner

st.set_page_config(page_title="관리", page_icon="⚙️", layout="wide")
require_owner()

st.title("관리")

t1, t2, t3 = st.tabs(["맥주 라인업", "프롬프트", "제약조건"])

with t1:
    st.caption("월 1회 교체. 스타일·도수·맛 특성이 비면 페어링이 추측으로 채워집니다.")
    st.info("beers 테이블 조회 후 표시합니다.")
    st.caption("T10b에서 구현 예정")

with t2:
    st.caption("prompts/*.yaml 을 화면에서 수정합니다.")
    st.selectbox("대상", ["p1_analyst", "p2_chef", "p3_marketer", "p4_consultant",
                          "common_rules"])
    st.info("파일 내용을 불러와 편집합니다.")
    st.caption("W5 이후 구현 예정")

with t3:
    st.caption("폐기 사유를 긍정형 제약으로 변환해 누적합니다. (설계 결정 D2)")
    st.info("constraints.yaml 항목을 표시합니다.")
    st.caption("T34에서 구현 예정")
