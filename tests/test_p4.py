"""
(4) 컨설턴트 프롬프트 확인 — T12 검증용

(1)→(2)→(3)→(4)를 실제로 이어 돌린다.
4단계가 모두 돌기 때문에 체인 통합 실행을 겸한다.
8/31 방문에서 보여드릴 샘플 기획안이 여기서 나온다.

실행
  python -m tests.test_p4                  화·목요일 (체인 전체)
  python -m tests.test_p4 --save           결과를 파일로 저장
  python -m tests.test_p4 --plan 52        저장된 기획안의 (1)~(3)으로 (4)만 2회
  python -m tests.test_p4 --plan 52 --times 3
"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from chain.checks import check_final, parse_beer_prices
from chain.gemini import call
from chain.inputs import (BOTTLING_INGREDIENTS, BOTTLING_SNS, MARGIN_REF,
                          NO_REC_REASON, NO_TREND_MENU, PAST_CASES,
                          WEATHER_PREF, build_beer_list, build_constraints,
                          build_events, build_partner_blockers,
                          build_partner_resources, build_partner_sns,
                          build_rec_reason, fetch_partner)
from chain.loader import build
from chain.runner import NO_ISSUES, NO_REJECTED
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
            constraints=rules["p2"], fewshot=NO_FEWSHOT,
            rejected=NO_REJECTED,
            prev_output=NO_ISSUES, issues=NO_ISSUES))
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
            constraints=rules["p3"], past_cases=PAST_CASES,
            prev_output=NO_ISSUES, issues=NO_ISSUES))
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
        prev_output="(없음 — 첫 생성이다)",
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
    for r in out.get("안") or []:
        beer = (r.get("페어링_맥주") or {}).get("메뉴명", "?")
        ev = (r.get("이벤트") or {}).get("명칭", "?")
        print(f"  {r.get('안_id')} [{r.get('접근')}]  {r.get('메뉴명')}")
        print(f"        페어링 {beer} / 판매가 {r.get('판매가_제안')}원")
        print(f"        값근거 {str(r.get('판매가_설명'))[:60]}")
        print(f"        이벤트 {ev}")
        print(f"        사유   {str(r.get('선정_사유'))[:60]}")
        for risk in (r.get("예상_리스크") or [])[:2]:
            print(f"        리스크 {risk[:60]}")

        # 어느 안이든 협력사에 보낼 제안서가 될 수 있다 — 4필드가 안마다 있다
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

    issues = check_final(out, p2, parse_beer_prices(beer_text)).all
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


def rerun_p4(plan_id: int, times: int = 2) -> None:
    """
    저장된 기획안의 (1)~(3) 출력을 그대로 넣고 (4)만 다시 돌린다.

    (4) 프롬프트를 고칠 때마다 체인을 처음부터 돌리면 30초씩 들고, 앞 단계 출력이
    매번 달라져 무엇 때문에 바뀐 것인지 알 수 없다. 입력을 고정해야 비교가 된다.
    LLM 출력은 흔들리므로 기본 2회 — 한 번 나온 것이 재현되는지 본다.

    실행  python -m tests.test_p4 --plan 52
          python -m tests.test_p4 --plan 52 --times 3
    """
    from db.client import get_client

    row = (get_client().table("plans")
           .select("id,partner_id,target_date,p1_output,p2_output,p3_output")
           .eq("id", plan_id).single().execute().data)
    partner = (get_client().table("partners").select("*")
               .eq("id", row["partner_id"]).single().execute().data)
    beer_text = build_beer_list()
    rules = build_constraints()

    print("=" * 64)
    print(f"plan {row['id']} · {partner['name']} · 실행일 {row['target_date']} · {times}회")
    print("=" * 64)

    for n in range(1, times + 1):
        out, ms = call(build(
            "p4_consultant",
            p1_output=json.dumps(row["p1_output"], ensure_ascii=False),
            p2_output=json.dumps(row["p2_output"], ensure_ascii=False),
            p3_output=json.dumps(row["p3_output"], ensure_ascii=False),
            events=build_events(date.fromisoformat(row["target_date"])),
            beer_list=beer_text,
            partner_resources=build_partner_resources(partner),
            rec_reason=build_rec_reason(partner),
            constraints=rules["p4"], fewshot=NO_FEWSHOT,
            prev_output=NO_ISSUES, issues=NO_ISSUES))

        print(f"\n[{n}회 · {ms/1000:.1f}초]")
        for e in out.get("제외") or []:
            print(f"  제외 {e.get('안_id')} — {str(e.get('제외_사유'))[:70]}")
        for r in out.get("안") or []:
            print(f"  {r.get('안_id')} [{r.get('접근')}] {r.get('메뉴명')} "
                  f"— {r.get('판매가_제안')}원")
            print(f"     매입   {(r.get('매입') or {}).get('바틀링_제안_매입가')}")
            print(f"     값근거 {r.get('판매가_설명')}")
            print(f"     배경   {r.get('배경')}")

        issues = check_final(out, row["p2_output"], parse_beer_prices(beer_text)).all
        for i in issues:
            print(f"     · {i}")


if __name__ == "__main__":
    if "--plan" in sys.argv:
        i = sys.argv.index("--plan")
        times = (int(sys.argv[sys.argv.index("--times") + 1])
                 if "--times" in sys.argv else 2)
        rerun_p4(int(sys.argv[i + 1]), times)
    else:
        save = "--save" in sys.argv
        for dow in (1, 3):
            run(f"{WEEKDAYS[dow]}요일", latest_weekday(dow), save=save)
