"""
페르소나 체인 실행기 — (1) → (2) → (3) → (4) 순차

[담당] B
[소요] 약 58초 (4콜)
"""
from chain.gemini import call
from chain.loader import build


def run(context: str, target_date: str, beer_list: str, kitchen: str,
        partner_res: str, partner_blockers: str, constraints: str,
        fewshot: str, bottling_sns: str, partner_sns: str,
        events: str, rec_reason: str, on_step=None) -> dict:
    """
    on_step: 진행 상황 콜백 (Streamlit st.status 연동용)
    """
    total_ms = 0

    def step(n, label, name, **kw):
        nonlocal total_ms
        if on_step:
            on_step(n, label)
        out, ms = call(build(name, **kw))
        total_ms += ms
        return out

    p1 = step(1, "상권 분석 중...", "p1_analyst",
              context=context, target_date=target_date)

    p2 = step(2, "협업 메뉴 개발 중...", "p2_chef",
              p1_output=p1, beer_list=beer_list, kitchen_constraints=kitchen,
              partner_resources=partner_res, partner_blockers=partner_blockers,
              constraints=constraints, fewshot=fewshot)

    p3 = step(3, "홍보 기획 중...", "p3_marketer",
              p1_output=p1, p2_output=p2,
              bottling_sns=bottling_sns, partner_sns=partner_sns, events=events)

    p4 = step(4, "최종 검토 중...", "p4_consultant",
              p1_output=p1, p2_output=p2, p3_output=p3,
              rec_reason=rec_reason, constraints=constraints, fewshot=fewshot)

    return {"p1": p1, "p2": p2, "p3": p3, "final": p4, "latency_ms": total_ms}
