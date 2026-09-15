"""
(2) 셰프 프롬프트 확인 — T12 검증용

(1)의 실제 출력을 받아 (2)만 이어 실행한다.
체인 전체를 돌리기 전에 메뉴 생성 단계가 제약을 지키는지 본다.

실행: python -m tests.test_p2
"""
import json
from datetime import date, datetime, timedelta, timezone

from chain.checks import (check_menu, check_menu_sources,
                          parse_beers)
from chain.gemini import call
from chain.inputs import (BOTTLING_INGREDIENTS, MARGIN_REF, NO_TREND_MENU,
                          WEATHER_PREF, build_beer_list, build_constraints,
                          build_partner_blockers, build_partner_resources,
                          fetch_partner)
from chain.loader import build
from chain.runner import NO_REJECTED
from context.builder import build as build_context

KST = timezone(timedelta(hours=9))
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

# fewshot.yaml 은 아직 비어 있다. 채택 사례가 없으므로 지어내지 않는다.
# constraints 는 8/31 사례에서 뽑은 7건이 들어와 실제 값을 쓴다.
NO_FEWSHOT = "(없음 — 채택 사례가 아직 없다)"

def latest_weekday(dow: int) -> date:
    """가장 최근에 지나간 해당 요일. 오늘이 그 요일이면 오늘."""
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
    beers = parse_beers(beer_text)
    print(f"협력사 {partner['name']} / 맥주 {len(beers)}종\n")

    # (1) 상권분석가
    # 협력사 업종에 맞는 매출 프로파일을 싣기 위해 category 를 넘긴다.
    # 넘기지 않으면 바틀링 업종만 실려 상대 업종의 매출 성향을 알 수 없다.
    ctx = build_context(target, partner_category=partner.get("category"))
    p1_prompt = build("p1_analyst", context=ctx,
                      target_date=target.isoformat())
    try:
        p1, ms1 = call(p1_prompt)
    except Exception as e:
        print(f"(1) 실패: {e}\n")
        return
    slots = p1.get("공략_시간대") or []
    print(f"(1) 완료 {ms1/1000:.1f}초 — 공략 시간대 {len(slots)}개")
    if not slots:
        print("    휴무일이라 (2)를 돌려도 의미가 없다. 건너뛴다.\n")
        return

    # (2) 셰프
    p2_prompt = build("p2_chef",
                      p1_output=json.dumps(p1, ensure_ascii=False),
                      beer_list=beer_text,
                      partner_resources=build_partner_resources(partner),
                      partner_blockers=build_partner_blockers(partner),
                      bottling_ingredients=BOTTLING_INGREDIENTS,
                      margin_ref=MARGIN_REF,
                      weather_pref=WEATHER_PREF,
                      trend_menu=NO_TREND_MENU,
                      constraints=build_constraints()["p2"],
                      fewshot=NO_FEWSHOT,
                      rejected=NO_REJECTED)
    print(f"(2) 프롬프트 {len(p2_prompt)}자\n")

    try:
        out, ms2 = call(p2_prompt)
    except Exception as e:
        print(f"(2) 실패: {e}\n")
        return

    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n소요 {(ms1+ms2)/1000:.1f}초 (1단계 {ms1/1000:.1f} + 2단계 {ms2/1000:.1f})")

    # 요약 — 눈으로 볼 지점
    print("-" * 64)
    for m in out.get("메뉴안") or []:
        pair = (m.get("페어링_맥주") or {}).get("메뉴명", "?")
        price = beers.get(pair, {}).get("price")
        tag = f"{price:.0f}원/ml" if price else "?"
        print(f"  {m.get('안_id')}. {m.get('메뉴명')} [{m.get('접근')}]")
        print(f"      페어링 {pair} ({tag})"
              f" / 매입 {m.get('협력사희망_매입가')}"
              f" / 정가합 {m.get('정가_합')} / 판매가 {m.get('판매가_제안')}")
        print(f"      보관 {m.get('보관_조건')} / 납품 {m.get('1회_납품_수량')}")

    issues = check_menu(out, beers) + check_menu_sources(out, partner)
    print("-" * 64)
    if issues:
        for i in issues:
            print(f"  · {i}")
    else:
        print("  제약 위반 없음")
    print()


if __name__ == "__main__":
    # 영업일 두 개로 확인한다. 월요일은 휴무라 (1)이 시간대를 비운다.
    for dow in (1, 3):
        run(f"{WEEKDAYS[dow]}요일", latest_weekday(dow))
