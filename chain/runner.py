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

from chain.checks import (Checked, check_final, check_menu,
                          check_menu_sources, check_promo, is_rank_reason,
                          parse_beer_prices, parse_beers)
from chain.gemini import call
from chain.inputs import NO_DATA
from chain.loader import build


# (4)가 첫 생성일 때 [직전 출력]·[직전 출력에서 발견된 문제] 자리에
# 들어가는 값. 빈 문자열을 넣으면 그 블록이 통째로 비어 보여, 검사를
# 안 한 것인지 통과한 것인지 구분되지 않는다.
NO_ISSUES = "(없음 — 첫 생성이다)"

# (2)가 첫 생성일 때 [직전에 낸 안과 실행 불가 사유] 자리에 들어가는 값.
NO_REJECTED = "(없음 — 첫 생성이다)"

# 앞 단계로 되감는 횟수 상한. (2)로 가든 (3)으로 가든 각각 한 번까지다.
#
# 되감으면 (2)(3)(4)를 다시 돌아 15초가 붙는다. 그래도 되감는 이유는
# 실행 불가 판정을 받은 안이 섞인 채로 나가면 대표님이 고를 수 있는
# 안이 그만큼 줄기 때문이다. 세 안을 나란히 놓고 고르는 것이 채택률의
# 전제다 (명세서 D4).
MAX_RESTART = 1

# 단계를 다시 부를 수 있는 횟수.
#
# 되감기와 몫을 나눠 쓴다. 합쳐 두었더니 사소한 재호출이 예산을 다 써서
# 정작 되감아야 할 때 되감지 못했다.
#
# (4)는 따로 센다 (9/22). (2)(3)이 앞에서 2회를 다 쓰면 (4) 검사가 걸려도
# 되돌릴 수 없었다 — 고정 테스트에서 포장안을 "확인 필요"로 뺀 오판이 그대로
# 나간 것이 세 번 중 두 번(1ec9494 3건, 4428a13 2건). 검사는 걸렸는데 예산이 0.
MAX_REDO = 2            # (2)(3) 합쳐서
MAX_REDO_FINAL = 1      # (4) 따로


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


def look(fn, *args, **kw) -> Checked:
    """
    검사를 돌리되 흐름은 끊지 않는다 (작업 원칙 ⑤).

    검사가 보는 것은 LLM 출력이라 형태가 어긋날 때가 있다. 목록이 올
    자리에 문장 하나가 오면 검사가 죽는데, 그것 때문에 20초 걸려 만든
    결과를 통째로 버리면 손해다.

    검사가 죽었다는 것은 출력 형태가 어긋났다는 뜻이다. 그래서 다시 부를
    것에 넣는다 — 같은 입력이라도 LLM 은 매번 다른 출력을 내므로 다시
    부르면 형태가 맞게 올 수 있다.
    """
    try:
        return fn(*args, **kw)
    except Exception as e:
        return Checked([f"출력 형태가 스키마와 맞지 않아 검사를 마치지 "
                        f"못했다 — {type(e).__name__}: {e}"], [])


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

        def call_p4(label: str, note: str, prev: dict | None = None) -> dict:
            # 다시 부를 때는 직전 출력을 함께 넘긴다. 걸린 곳만 고치고
            # 나머지는 그대로 옮기게 하려면 그것을 봐야 한다.
            return step(4, label, "p4_consultant",
                        p1_output=_j(result["p1"]),
                        p2_output=_j(result["p2"]),
                        p3_output=_j(result["p3"]),
                        # 행사 원본도 준다. (3)의 이벤트에는 판매 기간만 있어
                        # 배경에 행사 날짜를 쓸 때 그것과 섞였다 (9/22).
                        events=events,
                        beer_list=beer_list,
                        partner_resources=partner_res,
                        rec_reason=rec_reason,
                        constraints=constraints["p4"], fewshot=fewshot,
                        prev_output=_j(prev) if prev else NO_ISSUES,
                        issues=note)

        beers = parse_beers(beer_list)
        prices = parse_beer_prices(beer_list)
        rejected = NO_REJECTED
        extra = {"early": 0, "final": 0}   # 4콜 위에 더 부른 횟수 — (2)(3) / (4)
        promoed = 0                     # 홍보를 다시 짠 횟수

        def make(n, label, call, check):
            """
            한 단계를 만들고 검사한다. 걸리면 한 번 더 부른다.

            (2)(3)(4) 가 모두 같은 방식이다. 직전 출력과 무엇이 걸렸는지를
            함께 주고 다시 부르면, 걸린 곳만 고치고 나머지는 옮겨 적는다.
            한 번의 호출 안에서 만들고 스스로 검사할 수는 없으니, 코드가
            밖에서 보고 알려 주는 것이다.
            """
            out = call(label, NO_ISSUES, None)
            found = look(check, out)

            pool, limit = ("final", MAX_REDO_FINAL) if n == 4 else ("early", MAX_REDO)
            if found.redo and extra[pool] < limit:
                extra[pool] += 1
                result["rewinds"].append(found.redo)
                out = call(f"{label.rstrip('.')} — "
                           f"{len(found.redo)}건 보완 중...",
                           "\n".join(f"- {x}" for x in found.redo), out)
                found = look(check, out)

            result["issues"] += found.all
            return out

        def check_p2(out) -> Checked:
            # (1)의 소비_수준을 같이 넘긴다 — 객단가를 판매가로 베꼈는지 보려면
            found = check_menu(out, beers, result["p1"])
            if not partner:
                # 메뉴명에 나온 것이 어디서 오는지 보려면 협력사가 파는
                # 메뉴를 알아야 한다. 안 넘겼으면 이 검사만 건너뛴다.
                return found
            more = check_menu_sources(out, partner)
            return Checked(found.redo + more.redo, found.warn + more.warn)

        for attempt in range(MAX_RESTART + 1):
            # 되감으면 앞 시도에서 잡은 것은 버린다. 화면에 나가는 것은
            # 마지막 시도의 결과이므로, 버려진 시도의 경고까지 함께 보이면
            # 어느 것이 지금 결과의 문제인지 알 수 없다.
            result["issues"] = []
            result["rewinds"] = []

            def call_p2(label: str, note: str, prev: dict | None = None) -> dict:
                return step(
                    2, label, "p2_chef",
                    p1_output=_j(result["p1"]), beer_list=beer_list,
                    partner_resources=partner_res,
                    partner_blockers=partner_blockers,
                    bottling_ingredients=bottling_ingredients,
                    margin_ref=margin_ref, weather_pref=weather_pref,
                    trend_menu=trend_menu,
                    constraints=constraints["p2"], fewshot=fewshot,
                    rejected=rejected,
                    prev_output=_j(prev) if prev else NO_ISSUES,
                    issues=note)

            def call_p3(label: str, note: str, prev: dict | None = None) -> dict:
                return step(3, label, "p3_marketer",
                            p1_output=_j(result["p1"]),
                            p2_output=_j(result["p2"]),
                            target_date=target_date,
                            bottling_sns=bottling_sns,
                            partner_sns=partner_sns,
                            events=events,
                            constraints=constraints["p3"],
                            past_cases=past_cases,
                            prev_output=_j(prev) if prev else NO_ISSUES,
                            issues=note)

            result["p2"] = make(
                2,
                "협업 메뉴 개발 중..." if attempt == 0
                else "실행할 수 없는 안을 빼고 메뉴를 다시 만드는 중...",
                call_p2, check_p2)
            result["p3"] = make(
                3, "홍보 기획 중...", call_p3,
                lambda out: check_promo(out, result["p2"],
                                        date.fromisoformat(target_date),
                                        partner_sns=NO_DATA not in partner_sns,
                                        events=events))
            result["final"] = make(
                4, "최종 검토 중...", call_p4,
                lambda out: check_final(out, result["p2"], prices))

            # (4)가 홍보를 물리면 (3)부터 다시 짠다.
            #
            # (4)는 홍보 규칙을 받지 않아 직접 고칠 수 없다. 그리고 공통
            # 홍보축은 세 안이 함께 쓰는 값이라 하나만 고치면 나머지와
            # 어긋난다. 그래서 (4)가 고치는 대신 신호만 낸다.
            #
            # (3)(4)만 다시 돌면 되므로 (2) 되감기보다 싸다.
            why = result["final"].get("홍보_재생성_사유") or "사유 없음"
            if result["final"].get("홍보_재생성_필요") and promoed < MAX_RESTART:
                promoed += 1
                result["restarts"].append(f"홍보 다시 짜기 — {why}")
                result["p3"] = make(
                    3, "홍보를 다시 짜는 중...",
                    lambda label, note, prev=None: call_p3(
                        label, f"- 메뉴와 맞지 않는다: {why}", prev),
                    lambda out: check_promo(
                        out, result["p2"], date.fromisoformat(target_date),
                        partner_sns=NO_DATA not in partner_sns, events=events))
                result["final"] = make(
                    4, "최종 검토 중...", call_p4,
                    lambda out: check_final(out, result["p2"], prices))
            elif result["final"].get("홍보_재생성_필요"):
                result["issues"].append(f"홍보가 메뉴와 맞지 않는다 — {why}")

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
