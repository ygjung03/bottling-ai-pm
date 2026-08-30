"""
체인 실행기 동작 확인 — chain/runner.py 검증용

runner.run() 이 4단계를 순차로 도는지 본다.
tests/test_p4.py 와 겹쳐 보이지만 검증 대상이 다르다.

  test_p4   프롬프트가 제약을 지키는지  — 단계별로 직접 호출
  test_chain runner 가 입력을 옳게 넘기는지 — run() 한 번으로

runner 가 인자를 하나라도 빠뜨리면 여기서 드러난다.
실제로 p4_consultant 에 beer_list 를 넘기지 않아
맥주 단가가 0 으로 채워진 적이 있다.

실행: python -m tests.test_chain
"""
import json
import time
from datetime import date, datetime, timedelta, timezone

from chain.inputs import (BOTTLING_SNS, KITCHEN, NO_REC_REASON,
                          build_beer_list, build_events,
                          build_partner_blockers, build_partner_resources,
                          build_partner_sns, fetch_partner)
from chain.runner import run
from context.builder import build as build_context

KST = timezone(timedelta(hours=9))
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

NO_CONSTRAINTS = "(없음 — 폐기 사례가 아직 없다)"
NO_FEWSHOT = "(없음 — 채택 사례가 아직 없다)"


def latest_weekday(dow: int) -> date:
    today = datetime.now(KST).date()
    return today - timedelta(days=(today.weekday() - dow) % 7)


def on_step(n: int, label: str) -> None:
    print(f"  ({n}) {label}")


def main() -> None:
    # 화요일로 확인한다. 월요일은 휴무라 (1)이 공략 시간대를 비운다.
    target = latest_weekday(1)
    partner = fetch_partner()
    if not partner:
        print("협력사 없음 — python -m scripts.seed_partner 먼저 실행할 것")
        return

    print(f"대상 {target} ({WEEKDAYS[target.weekday()]}) / 협력사 {partner['name']}\n")

    # 하드코딩하지 않는다. 화면(T22)이 넘길 값과 같은 경로로 만든다.
    args = dict(
        context=build_context(target, partner_category=partner.get("category")),
        target_date=target.isoformat(),
        beer_list=build_beer_list(),
        kitchen=KITCHEN,
        partner_res=build_partner_resources(partner),
        partner_blockers=build_partner_blockers(partner),
        constraints=NO_CONSTRAINTS,
        fewshot=NO_FEWSHOT,
        bottling_sns=BOTTLING_SNS,
        partner_sns=build_partner_sns(partner),
        events=build_events(target),
        rec_reason=NO_REC_REASON,
    )

    print("입력 크기")
    for k, v in args.items():
        print(f"  {k:18} {len(str(v)):>6}자")
    print()

    print("체인 실행")
    t0 = time.perf_counter()
    try:
        r = run(on_step=on_step, **args)
    except TypeError as e:
        # runner 의 인자 이름이 바뀌면 여기서 걸린다
        print(f"\n인자 불일치: {e}")
        raise SystemExit(1)
    except Exception as e:
        print(f"\n실패: {e}")
        raise SystemExit(1)

    sec = time.perf_counter() - t0
    print(f"\n완료 — 총 {sec:.1f}초 (LLM {r['latency_ms']/1000:.1f}초)")

    # 단계별 산출물이 실제로 왔는지
    print()
    print("=" * 56)
    print("단계별 출력")
    print("=" * 56)

    slots = r["p1"].get("공략_시간대") or []
    print(f"  (1) 공략 시간대 : {len(slots)}개")
    for s in slots:
        print(f"        {s.get('시작')}~{s.get('종료')} ({s.get('근거_건수')})")

    menus = r["p2"].get("메뉴안") or []
    print(f"  (2) 메뉴안      : {len(menus)}개")
    for m in menus:
        print(f"        {m.get('안_id')}. {m.get('메뉴명')} "
              f"— {(m.get('페어링_맥주') or {}).get('메뉴명')}")

    plans = r["p3"].get("안별_기획") or []
    print(f"  (3) 안별 기획   : {len(plans)}개")

    ranks = r["final"].get("순위") or []
    print(f"  (4) 순위        : {len(ranks)}개")
    for rk in ranks:
        beer = rk.get("페어링_맥주") or {}
        print(f"        {rk.get('순위')}위 {rk.get('메뉴명')} "
              f"— {beer.get('메뉴명')} {beer.get('원_ml')}원/ml")

    # runner 가 입력을 빠뜨리면 나타나는 증상
    print()
    print("-" * 56)
    issues = []
    if len(menus) != 3:
        issues.append(f"메뉴안 {len(menus)}개 — 3개여야 함")
    if len(plans) != len(menus):
        issues.append(f"안별 기획 {len(plans)}개 — 메뉴안과 불일치")
    if not ranks:
        issues.append("순위 없음")
    for rk in ranks:
        price = (rk.get("페어링_맥주") or {}).get("원_ml")
        if not price:
            issues.append(f"{rk.get('안_id')}: 맥주 단가가 비어 있음 "
                          f"— runner 가 beer_list 를 넘기지 않았을 수 있다")

    if issues:
        for i in issues:
            print(f"  · {i}")
    else:
        print("  이상 없음")


if __name__ == "__main__":
    main()
