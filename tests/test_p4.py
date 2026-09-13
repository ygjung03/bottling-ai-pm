"""
(4) 컨설턴트 프롬프트 확인 — T12 검증용

(1)→(2)→(3)→(4)를 실제로 이어 돌린다.
4단계가 모두 돌기 때문에 체인 통합 실행을 겸한다.
8/31 방문에서 보여드릴 샘플 기획안이 여기서 나온다.

실행
  python -m tests.test_p4              화·목요일
  python -m tests.test_p4 --save       결과를 파일로 저장
"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from chain.checks import check, parse_beer_prices
from chain.gemini import call
from chain.inputs import (BOTTLING_INGREDIENTS, BOTTLING_SNS, MARGIN_REF,
                          NO_REC_REASON, NO_TREND_MENU, PAST_CASES,
                          WEATHER_PREF, build_beer_list, build_constraints,
                          build_events, build_partner_blockers,
                          build_partner_resources, build_partner_sns,
                          fetch_partner)
from chain.loader import build
from context.builder import build as build_context

KST = timezone(timedelta(hours=9))
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

NO_FEWSHOT = "(없음 — 채택 사례가 아직 없다)"

OUT_DIR = Path("tests/out")


def latest_weekday(dow: int) -> date:
    today = datetime.now(KST).date()
    return today - timedelta(days=(today.weekday() - dow) % 7)



def run(label: str, target: date, save: bool = False) -> None:
    dow = WEEKDAYS[target.weekday()]
    print("=" * 64)
    print(f"{label} — {target} ({dow})")
    print("=" * 64)

    partner = fetch_partner()
    if not partner:
        print("협력사 없음 — python -m scripts.seed_partner 먼저 실행할 것\n")
        return

    beer_text = build_beer_list()
    ctx = build_context(target, partner_category=partner.get("category"))
    ms = {}

    # (1)
    try:
        p1, ms["p1"] = call(build("p1_analyst", context=ctx,
                                  target_date=target.isoformat()))
    except Exception as e:
        print(f"(1) 실패: {e}\n")
        return
    if not (p1.get("공략_시간대") or []):
        print("(1) 공략 시간대 없음 — 휴무일이므로 건너뛴다.\n")
        return
    print(f"(1) 완료 {ms['p1']/1000:.1f}초")

    # (2)
    rules = build_constraints()
    partner_res = build_partner_resources(partner)
    try:
        p2, ms["p2"] = call(build(
            "p2_chef",
            p1_output=json.dumps(p1, ensure_ascii=False),
            beer_list=beer_text,
            partner_resources=partner_res,
            partner_blockers=build_partner_blockers(partner),
            bottling_ingredients=BOTTLING_INGREDIENTS,
            margin_ref=MARGIN_REF, weather_pref=WEATHER_PREF,
            trend_menu=NO_TREND_MENU,
            constraints=rules["p2"], fewshot=NO_FEWSHOT))
    except Exception as e:
        print(f"(2) 실패: {e}\n")
        return
    print(f"(2) 완료 {ms['p2']/1000:.1f}초 — 메뉴안 {len(p2.get('메뉴안') or [])}개")

    # (3)
    try:
        p3, ms["p3"] = call(build(
            "p3_marketer",
            p1_output=json.dumps(p1, ensure_ascii=False),
            p2_output=json.dumps(p2, ensure_ascii=False),
            target_date=target.isoformat(),
            bottling_sns=BOTTLING_SNS,
            partner_sns=build_partner_sns(partner),
            events=build_events(target),
            constraints=rules["p3"], past_cases=PAST_CASES))
    except Exception as e:
        print(f"(3) 실패: {e}\n")
        return
    print(f"(3) 완료 {ms['p3']/1000:.1f}초")

    # (4)
    p4_prompt = build(
        "p4_consultant",
        p1_output=json.dumps(p1, ensure_ascii=False),
        p2_output=json.dumps(p2, ensure_ascii=False),
        p3_output=json.dumps(p3, ensure_ascii=False),
        beer_list=beer_text, partner_resources=partner_res,
        rec_reason=NO_REC_REASON,
        constraints=rules["p4"], fewshot=NO_FEWSHOT,
        issues="(없음 — 첫 생성이다)")
    print(f"(4) 프롬프트 {len(p4_prompt)}자\n")

    try:
        out, ms["p4"] = call(p4_prompt)
    except Exception as e:
        print(f"(4) 실패: {e}\n")
        return

    print(json.dumps(out, ensure_ascii=False, indent=2))
    total = sum(ms.values()) / 1000
    print(f"\n소요 {total:.1f}초 (" +
          " + ".join(f"{v/1000:.1f}" for v in ms.values()) + ")")

    # 요약 — 대표에게 보이는 형태
    print("-" * 64)
    for r in out.get("순위") or []:
        beer = (r.get("페어링_맥주") or {}).get("메뉴명", "?")
        ev = (r.get("이벤트") or {}).get("명칭", "?")
        print(f"  {r.get('순위')}위  {r.get('메뉴명')} [{r.get('안_id')}]")
        print(f"        페어링 {beer} / 판매가 {r.get('판매가_제안')}원"
              f" / 준비 {r.get('소요_기간')}")
        print(f"        이벤트 {ev}")
        print(f"        사유   {str(r.get('선정_사유'))[:60]}")
        for risk in (r.get("예상_리스크") or [])[:2]:
            print(f"        리스크 {risk[:60]}")

        # 1위는 협력사에 보낼 제안서가 된다 (명세서 4-2-1)
        if r.get("순위") != 1:
            continue
        deal = r.get("매입") or {}
        roles = r.get("역할분담") or {}
        gains = r.get("상호_이익") or {}
        print(f"        매입   {deal.get('바틀링_제안_매입가')} "
              f"(협의 필요 {deal.get('협의_필요')})")
        print(f"        역할   바틀링 {roles.get('바틀링')}")
        print(f"               협력사 {roles.get('협력사')}")
        print(f"        이익   바틀링 {str(gains.get('바틀링'))[:50]}")
        print(f"               협력사 {str(gains.get('협력사'))[:50]}")
        print(f"        배경   {str(r.get('배경'))[:60]}")
    for e in out.get("제외") or []:
        print(f"  제외  {e.get('안_id')} — {str(e.get('제외_사유'))[:60]}")

    issues = check(out, p2, parse_beer_prices(beer_text))
    print("-" * 64)
    if issues:
        for i in issues:
            print(f"  · {i}")
    else:
        print("  제약 위반 없음")

    if save:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / f"plan_{target.isoformat()}.json"
        path.write_text(json.dumps(
            {"target_date": target.isoformat(), "context": ctx,
             "p1": p1, "p2": p2, "p3": p3, "final": out,
             "latency_ms": sum(ms.values())},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  저장 {path}")
    print()


if __name__ == "__main__":
    save = "--save" in sys.argv
    for dow in (1, 3):
        run(f"{WEEKDAYS[dow]}요일", latest_weekday(dow), save=save)
