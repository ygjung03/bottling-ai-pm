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

[2026-09-14] 검증 루프 2단계 — (4) 되감기.
  검사에서 걸린 것을 (4)에게 알려 주고 다시 부른다. 한 번의 호출 안에서
  만들고 검사하므로 (4)가 자기가 놓친 것을 스스로 잡을 수는 없다.
  코드가 밖에서 보고 되돌려 주면 고칠 기회가 생긴다.

  (2)·(3) 되감기는 3단계로 미뤘다. 앞 단계를 되돌리면 그 뒤가 모두
  다시 실행되어 비용이 크고, 대부분은 (4) 재호출로 끝난다
  (docs/검증루프_도입안.md 3장).
"""
import json
from datetime import date

from chain.checks import (check_final, check_menu, check_menu_sources,
                          check_promo, is_rank_reason, parse_beer_prices,
                          parse_beers)
from chain.gemini import call
from chain.inputs import NO_DATA
from chain.loader import build


# (4)가 첫 생성일 때 [직전 출력]·[직전 출력에서 발견된 문제] 자리에
# 들어가는 값. 빈 문자열을 넣으면 그 블록이 통째로 비어 보여, 검사를
# 안 한 것인지 통과한 것인지 구분되지 않는다.
NO_ISSUES = "(없음 — 첫 생성이다)"

# (2)가 첫 생성일 때 [직전에 낸 안과 실행 불가 사유] 자리에 들어가는 값.
NO_REJECTED = "(없음 — 첫 생성이다)"

# 되감기 횟수 상한.
#
# 1 로 둔다. 두 번 불러 안 고쳐지면 세 번째도 대개 안 고쳐지고,
# 한 번 되돌릴 때마다 7초쯤 늘어난다. 지금 체인이 18~30초인데
# 명세서 목표가 19~24초다.
MAX_REWIND = 1

# (2)까지 되감는 횟수 상한.
#
# 되감으면 (2)(3)(4)를 다시 돌아 15초가 붙는다. 그래도 되감는 이유는
# 실행 불가 판정을 받은 안이 섞인 채로 나가면 대표님이 고를 수 있는
# 안이 그만큼 줄기 때문이다. 세 안을 나란히 놓고 고르는 것이 채택률의
# 전제다 (명세서 D4).
MAX_RESTART = 1


def _j(obj) -> str:
    """
    프롬프트에 넣을 JSON 문자열.

    dict 를 그대로 넘기면 loader.render() 의 str(v) 가 파이썬 repr 로 만든다.
    작은따옴표와 True/False/None 이 섞여, 검증 스크립트(json.dumps)와
    다른 입력이 된다. 그러면 tests 에서 잰 통과율이 운영에서 그대로
    나온다는 보장이 없어 고정 테스트셋(명세서 5-5)의 전제가 흔들린다.
    """
    return obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)


def rejected_note(p2: dict, excluded: list[dict]) -> str:
    """
    (2)에게 되돌려 보낼 쪽지. 무엇을 그대로 두고 무엇을 바꿀지 적는다.

    빠진 것만 바꾸게 하려면 살아남은 안도 함께 보여야 한다. 사유만
    넘기면 세 안을 통째로 다시 만들어, 이미 통과한 안까지 바뀐다.

    안의 내용을 통째로 넘긴다. 처음에는 "A. 두바이쫀득 붕어빵 (단품)"
    처럼 이름만 한 줄로 넘겼는데, 그대로 두라고 한 안까지 (2)가 새로
    만들었다. 판매가가 9,705원에서 4,500원이 되고 페어링 맥주도 바뀌었다.
    이름만 받으면 무엇을 그대로 적어야 할지 알 수 없으니 당연한 결과다.
    """
    why = {e.get("안_id"): e.get("제외_사유") or "사유 없음" for e in excluded}

    keep, redo = [], []
    for m in p2.get("메뉴안") or []:
        body = json.dumps(m, ensure_ascii=False, indent=2)
        if m.get("안_id") in why:
            redo.append(f"실행 불가 사유: {why[m.get('안_id')]}\n{body}")
        else:
            keep.append(body)

    # (4)가 (2)에 없는 안_id 를 뱉으면 redo 가 빈다. 그때도 사유는 넘긴다
    if not redo:
        redo = [f"{k}안 — 실행 불가 사유: {v} (해당 메뉴를 찾지 못했다)"
                for k, v in why.items()]

    parts = []
    if keep:
        parts.append("[그대로 둘 안] — 아래 내용을 그대로 다시 낸다\n"
                     + "\n".join(keep))
    parts.append("[다시 만들 안]\n" + "\n\n".join(redo))
    return "\n\n".join(parts)


def warn(fn, *args, **kw) -> list[str]:
    """
    검사를 돌리되 흐름은 끊지 않는다 (작업 원칙 ⑤).

    검사가 보는 것은 LLM 출력이라 형태가 어긋날 때가 있다. 목록이 올
    자리에 문장 하나가 오면 검사가 죽는데, 그것 때문에 20초 걸려 만든
    결과를 통째로 버리면 손해다. 검사가 죽은 것도 경고 한 줄로 남긴다.
    """
    try:
        return fn(*args, **kw)
    except Exception as e:
        return [f"검사를 마치지 못했다 ({fn.__name__}) — {type(e).__name__}: {e}"]


def run(context: str, target_date: str, beer_list: str,
        partner_res: str, partner_blockers: str, bottling_ingredients: str,
        margin_ref: str, weather_pref: str, trend_menu: str,
        constraints: dict, fewshot: str,
        bottling_sns: str, partner_sns: str, events: str, past_cases: str,
        rec_reason: str, partner: dict | None = None,
        on_step=None) -> dict:
    """
    on_step: 진행 상황 콜백 (Streamlit st.status 연동용)

    partner 는 (2) 검사에 쓴다. 메뉴명에 나온 것이 협력사가 파는 것인지
    보려면 필요하다. None 이면 그 검사만 건너뛴다.

    constraints 만 문자열이 아니라 dict 다. 규칙이 단계별로 갈려
    {"p2": ..., "p3": ..., "p4": ...} 형태로 온다 (명세서 1-5).
    chain.inputs.build_constraints() 가 만든다.

    반환
      p1~p3, final   단계별 출력. 끊긴 뒤의 단계는 None 이다
      latency_ms     LLM 소요 합계 (429 대기는 빼고 잰다)
      issues         되돌린 뒤에도 남은 것. 화면에 경고로 띄운다 (명세서 5-1)
      rewinds        (4) 재호출마다 그때 걸린 항목. 비어 있으면 한 번에 통과한 것
      restarts       (2)까지 되감을 때마다 (2)에게 넘긴 쪽지
      error          체인이 끊긴 사유. 이때도 앞 단계 결과는 살아 있다

    [주의] 예외를 밖으로 던지지 않는다. 17～20초짜리 체인에서 (3)이 죽었다고
      (1)(2)를 버리면 그냥 손해다. 호출자는 error 를 봐야 한다.
    """
    total_ms = 0
    result: dict = {
        "p1": None, "p2": None, "p3": None, "final": None,
        "latency_ms": 0, "issues": [], "rewinds": [], "restarts": [],
        "error": None,
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

        def call_p4(note: str, prev: dict | None = None) -> dict:
            # 되돌릴 때는 직전 출력을 함께 넘긴다. 걸린 곳만 고치고
            # 나머지는 그대로 옮기게 하려면 그것을 봐야 한다.
            return step(4, "최종 검토 중...", "p4_consultant",
                        p1_output=_j(result["p1"]),
                        p2_output=_j(result["p2"]),
                        p3_output=_j(result["p3"]),
                        beer_list=beer_list,
                        partner_resources=partner_res,
                        rec_reason=rec_reason,
                        constraints=constraints["p4"], fewshot=fewshot,
                        prev_output=_j(prev) if prev else NO_ISSUES,
                        issues=note)

        beers = parse_beers(beer_list)
        prices = parse_beer_prices(beer_list)
        rejected = NO_REJECTED

        for attempt in range(MAX_RESTART + 1):
            # 되감으면 앞 시도에서 잡은 것은 버린다. 화면에 나가는 것은
            # 마지막 시도의 결과이므로, 버려진 시도의 경고까지 함께 보이면
            # 어느 것이 지금 결과의 문제인지 알 수 없다.
            result["issues"] = []
            result["rewinds"] = []

            result["p2"] = step(
                2,
                "협업 메뉴 개발 중..." if attempt == 0
                else "실행할 수 없는 안을 빼고 메뉴를 다시 만드는 중...",
                "p2_chef",
                p1_output=_j(result["p1"]), beer_list=beer_list,
                partner_resources=partner_res,
                partner_blockers=partner_blockers,
                bottling_ingredients=bottling_ingredients,
                margin_ref=margin_ref, weather_pref=weather_pref,
                trend_menu=trend_menu,
                constraints=constraints["p2"], fewshot=fewshot,
                rejected=rejected)

            # 여기서 걸린 것은 화면에 알리는 데서 멈춘다. 되감는 것은
            # (4)가 실행 불가로 판정했을 때뿐이다 — 명세서 5-1 도
            # "재생성까지 하는 것은 A1·A2뿐이며 나머지는 화면에 경고로
            # 표시한다"고 정해 두었다.
            result["issues"] += warn(check_menu, result["p2"], beers)
            if partner:
                # 메뉴명에 나온 것이 어디서 오는지 보려면 협력사가 파는
                # 메뉴를 알아야 한다. 안 넘겼으면 이 검사만 건너뛴다.
                result["issues"] += warn(check_menu_sources,
                                         result["p2"], partner)

            result["p3"] = step(3, "홍보 기획 중...", "p3_marketer",
                                p1_output=_j(result["p1"]),
                                p2_output=_j(result["p2"]),
                                target_date=target_date,
                                bottling_sns=bottling_sns,
                                partner_sns=partner_sns,
                                events=events,
                                constraints=constraints["p3"],
                                past_cases=past_cases)

            result["issues"] += warn(
                check_promo, result["p3"], result["p2"],
                date.fromisoformat(target_date),
                partner_sns=NO_DATA not in partner_sns)

            result["final"] = call_p4(NO_ISSUES)

            # 검사에서 걸린 것을 (4)에게 알려 주고 다시 부른다.
            #
            # (4)가 자기 출력을 스스로 검사할 수는 없다. 한 번의 호출 안에서
            # 만들고 검사하므로 놓친 것은 놓친 채로 나온다. 코드가 밖에서
            # 보고 알려 주면 다시 만들 때 같은 실수를 피할 수 있다.
            found = check_final(result["final"], result["p2"], prices)

            for _ in range(MAX_REWIND):
                if not found:
                    break
                result["rewinds"].append(found)
                if on_step:
                    on_step(4, f"검토 결과 보완 중... ({len(found)}건)")
                result["final"] = call_p4("\n".join(f"- {x}" for x in found),
                                          prev=result["final"])
                found = check_final(result["final"], result["p2"], prices)

            # 되돌린 뒤에도 남은 것은 경고로 넘긴다. 무한히 돌리지 않는다.
            result["issues"] += found

            # (4)가 실행 불가로 뺀 안이 있으면 (2)부터 다시 만든다.
            #
            # (4)는 검수 1·2·6번 위반일 때만 안을 뺀다. 셋 다 "이 메뉴를
            # 실제로 만들어 낼 수 있는가"에 대한 것이라 되감을 곳이 (2)다.
            # 홍보가 메뉴와 어긋난 것은 제외 사유가 아니라 (4)가 직접
            # 고치므로 여기 오지 않는다.
            #
            # 판정하는 것은 코드가 아니라 (4)다. 그 안이 실제로 실행
            # 가능한지는 코드로 알 수 없다 — 협력사가 못 한다고 한 것인지,
            # 매장에 기구가 없는 것인지는 읽어야 나온다.
            #
            # 빠진 안을 그대로 두면 대표님이 고를 수 있는 안이 그만큼
            # 줄어든다. 세 안을 나란히 놓고 고르는 것이 전제다 (명세서 D4).
            # 만들 수 없어서 뺀 것만 (2)로 보낸다.
            #
            # "다른 안보다 매력이 떨어진다"로 뺀 것은 (4)의 판단 오류다.
            # (2)에게 보내도 고칠 것이 없어 같은 메뉴가 돌아온다.
            # 그 오류는 check_final 이 잡아 (4) 재호출에서 처리한다.
            blocked = [e for e in result["final"].get("제외") or []
                       if not is_rank_reason(e.get("제외_사유"))]
            if not blocked:
                break

            if attempt == MAX_RESTART:
                # 다시 만들었는데 또 빠졌다. 여기서 멈추고 경고로 넘긴다.
                for e in blocked:
                    result["issues"].append(
                        f"{e.get('안_id')}안 실행 불가 — "
                        f"{e.get('제외_사유') or '사유 없음'}")
                break

            note = rejected_note(result["p2"], blocked)
            result["restarts"].append(note)
            rejected = note

    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"

    result["latency_ms"] = total_ms
    return result
