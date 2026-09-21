"""
기획안 생성 화면의 페이지 머리.

9/21 시안(docs/ref/피그마_예시2.pdf)의 왼쪽 사이드바도 여기 있었으나, 같은 날
상단 내비게이션 바(app/theme.py apply_chrome)로 통일해 사이드바는
뺐다 (9/22 합의 — 큰 틀은 상단 바, 기획안 생성 화면 안쪽만 시안대로).

사용법
    from app.ui import page_header
    page_header("기획안 생성", "설명 한 줄")
"""
import streamlit as st


def page_header(title: str, subtitle: str) -> None:
    """시안의 페이지 머리 — 큰 제목과 회색 설명 한 줄."""
    st.markdown(
        f'<div style="font-size:1.9rem; font-weight:800; color:#0F172A; margin:4px 0 2px">'
        f'{title}</div>'
        f'<div style="color:#64748B; font-size:0.95rem; margin-bottom:22px">{subtitle}</div>',
        unsafe_allow_html=True)