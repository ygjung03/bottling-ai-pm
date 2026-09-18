"""
인증 — 대표님 비밀번호

[2026-09-17] 협력사 초대 코드로 여는 화면을 뺐다. 앱은 대표님만 쓴다.
       협력사 입력은 구글 폼으로 받고, 어느 협력사의 답인지는 폼의
       「확인 코드」를 `partners.invite_code` 와 맞춰 가린다
       (scripts/google_form_sync.gs). 코드 발급은 그대로 파트너 추천
       화면과 scripts/new_partner.py 가 한다.

[중요] Streamlit 멀티페이지는 URL 직접 접근이 가능하다.
       localhost:8501/기획안_생성 을 주소창에 치면 사이드바를 거치지 않는다.
       따라서 각 페이지 첫 줄에서 매번 검사해야 한다.

사용법
    from app.auth import require_owner
    require_owner()          # 대표님 전용 페이지 맨 위
"""
import os

import streamlit as st

# .env 를 읽는 것은 config.settings 다. 이 모듈은 설정값을 직접 쓰지 않지만
# 로그인 화면이 앱에서 가장 먼저 열리므로, 여기서 import 하지 않으면
# OWNER_PASSWORD 가 .env 에 있어도 os.getenv 에 없다. 전에는 db.client 를
# 거쳐 우연히 읽혔는데 그 import 를 빼면서 로그인이 막힌 적이 있다(9/18).
import config.settings  # noqa: F401

SS_OWNER = "auth_owner"


def _password() -> str:
    """
    st.secrets 우선, 없으면 환경변수.

    [2026-09-08] 기본값을 없앴다.

    전에는 둘 다 비면 개발용 기본값으로 통과했다. 저장소가 공개라
    그 값이 그대로 읽혔고, 설정을 빠뜨려도 아무 표시 없이 열려서
    빠뜨린 사실조차 알 수 없었다.

    지금은 설정이 없으면 로그인 화면에서 멈춘다. 배포(T27) 때
    Streamlit Cloud secrets 에 OWNER_PASSWORD 를 넣어야 한다.
    """
    try:
        return st.secrets["OWNER_PASSWORD"]
    except Exception:
        pass

    pw = os.getenv("OWNER_PASSWORD")
    if not pw:
        st.error("OWNER_PASSWORD 가 설정되지 않았습니다.")
        st.caption("로컬은 .env, 배포는 Streamlit Cloud secrets 에 넣습니다.")
        st.stop()
    return pw


def is_owner() -> bool:
    return bool(st.session_state.get(SS_OWNER))


def login_form() -> None:
    """진입점에서 호출. 로그인 폼을 그린다."""
    st.markdown("#### 로그인")
    pw = st.text_input("비밀번호", type="password", label_visibility="collapsed",
                       placeholder="비밀번호")
    if st.button("입장", use_container_width=True):
        if pw == _password():
            st.session_state[SS_OWNER] = True
            st.rerun()
        else:
            st.error("비밀번호가 맞지 않습니다.")


def require_owner() -> None:
    """대표님 전용 페이지 맨 위에서 호출한다."""
    if is_owner():
        return
    st.title("바틀링 AI PM")
    st.caption("대표님 전용 화면입니다.")
    login_form()
    st.stop()


def logout() -> None:
    st.session_state.pop(SS_OWNER, None)
    st.rerun()
