"""
협력사 자원 입력 — 초대 코드로 접근하는 공개 페이지

[중요] 이 페이지만 대표님 로그인 없이 열린다.
       URL: .../협력사_입력?code=A7K2
       코드가 유효하지 않으면 어떤 정보도 노출하지 않는다.

작성 소요 3분 이내가 목표다. multiselect 기본 선택지를 미리 채워
타이핑을 줄인다.
"""
import _path  # noqa: F401  (프로젝트 루트를 sys.path 에 추가)
import streamlit as st

from app.auth import verify_invite, is_owner

st.set_page_config(page_title="협력사 정보 입력", page_icon="📋")

code = st.query_params.get("code", "")
partner = verify_invite(code)

if not partner and not is_owner():
    st.title("협력사 정보 입력")
    st.warning("유효한 링크로 접속해 주세요.")
    st.caption("바틀링에서 전달받으신 주소를 확인해 주십시오.")
    st.stop()

name = partner["name"] if partner else "(미리보기)"
st.title("협력사 정보 입력")
st.caption(f"{name} · 약 3분이면 끝납니다.")

st.info("**보유 식재료 · 보유 장비 · 절대 불가 조건**을 자세히 적어주실수록 "
        "실행 가능한 메뉴가 나옵니다.")

# TODO(T21): 실제 폼 구현 (명세서 4-1)
st.divider()
st.markdown("""
| # | 항목 | 필수 |
|---|---|---|
| 1 | 가게 이름 | O |
| 2 | 업종 | O |
| 3 | 대표 메뉴 | O |
| 4 | **보유 식재료** | O |
| 5 | **보유 장비** (이동 가능 여부 포함) | O |
| 6 | 협업 가능 형태 | O |
| 7 | 가능 일정 | O |
| 8 | SNS 채널·팔로워 | – |
| 9 | **절대 불가 조건** | O |
""")
st.caption("T21에서 구현 예정")
