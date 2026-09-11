"""
페르소나 체인 실행기 — (1) → (2) → (3) → (4) 순차

[담당] B
[소요] 약 19～24초 (4콜). 메뉴 이미지 생성은 여기에 포함되지 않는다

[2026-09-08] T42 — 완제품 매입 단일화 반영.
  kitchen 이 빠졌다. 협력사가 자기 장비로 만들어 오므로 바틀링 주방
  여건이 협업 기획에 개입하지 않는다 (기획서 6-1).
  margin_ref·weather_pref·trend_menu·past_cases 가 들어왔고,
  partner_res 가 (4)에도 간다 — 역할분담을 쓰려면 상대가 무엇을
  가졌는지 알아야 한다 (명세서 1-4).

[2026-09-08] 검증 루프 1단계 — 결함 넷 (docs/검증루프_도입안.md 4장).
  ① 프롬프트에 넣는 dict 를 JSON 으로 통일했다 (_j)
  ② 중간에 끊겨도 앞 단계 결과를 버리지 않는다 (error)
  ③ 재생성_필요 를 읽어 화면에 알린다 (issues)
  ④ 429 대기를 on_step 으로 노출한다

  되감기(검증 실패 → 해당 단계 재호출)는 2단계에서 붙인다.
  지금은 알리는 데서 멈춘다.
"""
import json

from chain.gemini import call
from chain.loader import build


def _j(obj) -> str:
    """
    프롬프트에 넣을 JSON 문자열.

    dict 를 그대로 넘기면 loader.render() 의 str(v) 가 파이썬 repr 로 만든다.
    작은따옴표와 True/False/None 이 섞여, 검증 스크립트(json.dumps)와
    다른 입력이 된다. 그러면 tests 에서 잰 통과율이 운영에서 그대로
    나온다는 보장이 없어 고정 테스트셋(명세서 5-5)의 전제가 흔들린다.
    """
    return obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)


def run(context: str, target_date: str, beer_list: str,
        partner_res: str, partner_blockers: str, bottling_ingredients: str,
        margin_ref: str, weather_pref: str, trend_menu: str,
        constraints: dict, fewshot: str,
        bottling_sns: str, partner_sns: str, events: str, past_cases: str,
        rec_reason: str, on_step=None) -> dict:
    """
    on_step: 진행 상황 콜백 (Streamlit st.status 연동용)

    constraints 만 문자열이 아니라 dict 다. 규칙이 단계별로 갈려
    {"p2": ..., "p3": ..., "p4": ...} 형태로 온다 (명세서 1-5).
    chain.inputs.build_constraints() 가 만든다.

    반환
      p1~p3, final   단계별 출력. 끊긴 뒤의 단계는 None 이다
      latency_ms     LLM 소요 합계 (429 대기는 빼고 잰다)
      issues         화면에 경고로 띄울 것 (명세서 5-1)
      error          체인이 끊긴 사유. 이때도 앞 단계 결과는 살아 있다

    [주의] 예외를 밖으로 던지지 않는다. 17～20초짜리 체인에서 (3)이 죽었다고
      (1)(2)를 버리면 그냥 손해다. 호출자는 error 를 봐야 한다.
    """
    total_ms = 0
    result: dict = {
        "p1": None, "p2": None, "p3": None, "final": None,
        "latency_ms": 0, "issues": [], "error": None,
    }

    def step(n, label, name, **kw):
        nonlocal total_ms
        if on_step:
            on_step(n, label)

        def on_wait(sec, attempt):  # noqa: ARG001 — 시도 횟수는 화면에 쓰지 않는다
            # 대기 중에도 화면이 멈춘 것처럼 보이지 않게 한다
            if on_step:
                on_step(n, f"{label} (호출 한도 도달 — {sec}초 대기 후 재시도)")

        out, ms = call(build(name, **kw), on_wait=on_wait)
        total_ms += ms
        return out

    try:
        result["p1"] = step(1, "상권 분석 중...", "p1_analyst",
                            context=context, target_date=target_date)

        result["p2"] = step(2, "협업 메뉴 개발 중...", "p2_chef",
                            p1_output=_j(result["p1"]), beer_list=beer_list,
                            partner_resources=partner_res,
                            partner_blockers=partner_blockers,
                            bottling_ingredients=bottling_ingredients,
                            margin_ref=margin_ref, weather_pref=weather_pref,
                            trend_menu=trend_menu,
                            constraints=constraints["p2"], fewshot=fewshot)

        result["p3"] = step(3, "홍보 기획 중...", "p3_marketer",
                            p1_output=_j(result["p1"]),
                            p2_output=_j(result["p2"]),
                            target_date=target_date,
                            bottling_sns=bottling_sns, partner_sns=partner_sns,
                            events=events,
                            constraints=constraints["p3"],
                            past_cases=past_cases)

        result["final"] = step(4, "최종 검토 중...", "p4_consultant",
                               p1_output=_j(result["p1"]),
                               p2_output=_j(result["p2"]),
                               p3_output=_j(result["p3"]),
                               beer_list=beer_list,
                               partner_resources=partner_res,
                               rec_reason=rec_reason,
                               constraints=constraints["p4"], fewshot=fewshot)

        # (4)를 다시 불러도 못 고치는 실패다. 세 안이 전부 실행 불가라는
        # 뜻이므로 원인은 (2)의 메뉴 3안에 있다. 되감을 곳이 (4)가 아니라
        # (2)라서 2단계로 미뤘고, 지금은 화면에 알리는 데서 멈춘다.
        if result["final"].get("재생성_필요"):
            why = result["final"].get("재생성_사유") or "사유 없음"
            result["issues"].append(
                f"세 안이 모두 실행 불가 — 메뉴 생성부터 다시 해야 한다 ({why})")

    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"

    result["latency_ms"] = total_ms
    return result
