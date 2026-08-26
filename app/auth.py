"""
인증 — 대표님 비밀번호 + 협력사 초대 코드

[중요] Streamlit 멀티페이지는 URL 직접 접근이 가능하다.
       localhost:8501/기획안_생성 을 주소창에 치면 사이드바를 거치지 않는다.
       따라서 각 페이지 첫 줄에서 매번 검사해야 한다.

사용법
    from app.auth import require_owner
    require_owner()          # 대표님 전용 페이지 맨 위
"""
import streamlit as st

from db.client import get_client

SS_OWNER = "auth_owner"
SS_PARTNER = "auth_partner"      # 초대 코드로 확인된 협력사 정보


def _password() -> str:
    """st.secrets 우선, 없으면 환경변수. 둘 다 없으면 개발용 기본값."""
    try:
        return st.secrets["OWNER_PASSWORD"]
    except Exception:
        import os
        return os.getenv("OWNER_PASSWORD", "bottling")


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


def verify_invite(code: str) -> dict | None:
    """
    초대 코드로 협력사를 조회한다.

    협력사는 로그인 없이 폼만 채운다. 코드가 곧 신원이므로
    코드가 유효하지 않으면 어떤 정보도 노출하지 않는다.
    """
    if not code:
        return None
    try:
        rows = (get_client().table("partners").select("*")
                .eq("invite_code", code.strip()).limit(1).execute().data)
        return rows[0] if rows else None
    except Exception:
        return None


def logout() -> None:
    for k in (SS_OWNER, SS_PARTNER):
        st.session_state.pop(k, None)
    st.rerun()
