"""
(3) 마케터 프롬프트 확인 — T12 검증용

(1)→(2)→(3)을 실제로 이어 돌린다.
가짜 입력을 만들면 실제 형식과 어긋나므로 앞 단계를 그대로 쓴다.

실행: python -m tests.test_p3
"""
import json
from datetime import date, datetime, timedelta, timezone

from chain.checks import check_promo
from chain.gemini import call
from chain.inputs import (BOTTLING_INGREDIENTS, BOTTLING_SNS, MARGIN_REF,
                          NO_DATA, NO_TREND_MENU, PAST_CASES, WEATHER_PREF,
                          build_beer_list, build_constraints, build_events,
                          build_partner_blockers, build_partner_resources,
                          build_partner_sns, fetch_partner)
from chain.loader import build
from chain.runner import NO_ISSUES, NO_REJECTED
from context.builder import build as build_context

KST = timezone(timedelta(hours=9))
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

NO_FEWSHOT = "(없음 — 채택 사례가 아직 없다)"

def latest_weekday(dow: int) -> date:
    today = datetime.now(KST).date()
    return today - timedelta(days=(today.weekday() - dow) % 7)


def run(label: str, target: date) -> None:
    dow = WEEKDAYS[target.weekday()]
    print("=" * 64)
    print(f"{label} — {target} ({dow})")
    print("=" * 64)

    partner = fetch_partner()
    if not partner:
        print("협력사 없음 — python -m scripts.seed_partner 먼저 실행할 것\n")
        return

    beer_text = build_beer_list()
    sns_known = NO_DATA not in BOTTLING_SNS
    print(f"협력사 {partner['name']} / 바틀링 SNS "
          f"{'확보' if sns_known else '미확보'}\n")

    # (1) 상권분석가
    # 협력사 업종에 맞는 매출 프로파일을 싣기 위해 category 를 넘긴다.
    # 넘기지 않으면 바틀링 업종만 실려 상대 업종의 매출 성향을 알 수 없다.
    ctx = build_context(target, partner_category=partner.get("category"))
    try:
        p1, ms1 = call(build("p1_analyst", context=ctx,
                             target_date=target.isoformat()))
    except Exception as e:
        print(f"(1) 실패: {e}\n")
        return
    if not (p1.get("공략_시간대") or []):
        print("(1) 공략 시간대 없음 — 휴무일이므로 건너뛴다.\n")
        return
    print(f"(1) 완료 {ms1/1000:.1f}초")

    # (2) 셰프
    rules = build_constraints()
    try:
        p2, ms2 = call(build(
            "p2_chef",
            p1_output=json.dumps(p1, ensure_ascii=False),
            beer_list=beer_text,
            partner_resources=build_partner_resources(partner),
            partner_blockers=build_partner_blockers(partner),
            bottling_ingredients=BOTTLING_INGREDIENTS,
            margin_ref=MARGIN_REF, weather_pref=WEATHER_PREF,
            trend_menu=NO_TREND_MENU,
            constraints=rules["p2"], fewshot=NO_FEWSHOT,
            rejected=NO_REJECTED,
            prev_output=NO_ISSUES, issues=NO_ISSUES))
    except Exception as e:
        print(f"(2) 실패: {e}\n")
        return
    menus = p2.get("메뉴안") or []
    print(f"(2) 완료 {ms2/1000:.1f}초 — 메뉴안 {len(menus)}개")

    # (3) 마케터
    p3_prompt = build(
        "p3_marketer",
        p1_output=json.dumps(p1, ensure_ascii=False),
        p2_output=json.dumps(p2, ensure_ascii=False),
        target_date=target.isoformat(),
        bottling_sns=BOTTLING_SNS,
        partner_sns=build_partner_sns(partner),
        events=build_events(target),
        constraints=rules["p3"], past_cases=PAST_CASES,
        prev_output=NO_ISSUES, issues=NO_ISSUES)
    print(f"(3) 프롬프트 {len(p3_prompt)}자\n")

    try:
        out, ms3 = call(p3_prompt)
    except Exception as e:
        print(f"(3) 실패: {e}\n")
        return

    print(json.dumps(out, ensure_ascii=False, indent=2))
    total = (ms1 + ms2 + ms3) / 1000
    print(f"\n소요 {total:.1f}초 "
          f"({ms1/1000:.1f} + {ms2/1000:.1f} + {ms3/1000:.1f})")

    # 요약 — 눈으로 볼 지점
    print("-" * 64)
    axis = out.get("공통_홍보축") or {}
    print(f"  타겟     {axis.get('타겟')}")
    print(f"  시점     {axis.get('공략_시점')}")
    print(f"  행사연계 {axis.get('행사_연계')}")
    print(f"  목표     {axis.get('목표')}")
    for c in axis.get("채널별_전략") or []:
        print(f"  채널     [{c.get('주체')}] {c.get('채널')} / {c.get('형식')}")
    for s in axis.get("홍보_일정") or []:
        print(f"  일정     {s.get('시점')} — {s.get('채널')} / {s.get('내용')}")
    for p in out.get("안별_기획") or []:
        name = next((m.get("메뉴명") for m in menus
                     if m.get("안_id") == p.get("안_id")), "?")
        print(f"\n  {p.get('안_id')}. {name}")
        print(f"      {(p.get('이벤트안') or {}).get('명칭')}")
        print(f"      \"{p.get('홍보_문구')}\"")
        print(f"      {' '.join(p.get('해시태그') or [])}")

    issues = check_promo(out, p2, target).all
    print("-" * 64)
    if issues:
        for i in issues:
            print(f"  · {i}")
    else:
        print("  제약 위반 없음")
    print()


if __name__ == "__main__":
    for dow in (1, 3):
        run(f"{WEEKDAYS[dow]}요일", latest_weekday(dow))
