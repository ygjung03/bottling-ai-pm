"""
협업 제안서 확인 — T44 검증용

체인 (1)～(4)를 실제로 돌리고, 그 출력으로 제안서를 만들어 본다.
가짜 입력을 만들면 실제 형식과 어긋나므로 실제 출력을 그대로 쓴다.

이 문서는 협력사에 그대로 나간다. 화면에서 눈으로 훑는 것만으로는
빠진 항목이나 어긋난 날짜를 매번 잡을 수 없다 — 실제로 실행 기간이
엉뚱한 달로 적힌 채 저장된 적이 있다.

실행: python -m tests.test_proposal
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

from app.proposal import (build_proposal, build_proposal_docx, missing_fields,
                          proposal_no)
from chain.inputs import (BOTTLING_INGREDIENTS, BOTTLING_SNS, MARGIN_REF,
                          NO_REC_REASON, NO_TREND_MENU, PAST_CASES,
                          WEATHER_PREF, build_beer_list, build_constraints,
                          build_events, build_partner_blockers,
                          build_partner_resources, build_partner_sns,
                          fetch_partner)
from chain.runner import run
from context.builder import build as build_context

KST = timezone(timedelta(hours=9))
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

# 제안서에 반드시 있어야 하는 절. 하나라도 빠지면 협력사가 무엇을 검토해야
# 하는지 알 수 없다 (명세서 1-4).
#
# 절 번호는 본문에서 매기므로 이름으로 찾는다.
SECTIONS = ["제안 개요", "제안 배경", "역할분담", "홍보 일정",
            "서로 얻는 것", "조건"]

# 실행 전 시점을 가리키는 표현. 날짜 대신 쓰였을 때 본다.
BEFORE_EXEC = re.compile(r"전|예고|티저|D-\s*\d")

# 내부에서만 쓰는 말. 협력사가 받는 문서에 나오면 안 된다.
INTERNAL = ["검수", "제약", "안_id", "재생성", "데이터 없음", "None", "null"]


def field(text: str, key: str) -> str:
    """제안서 본문에서 "실행 예정일   2026-09-17" 같은 줄의 값을 뽑는다."""
    m = re.search(rf"^\s*{re.escape(key)}\s{{2,}}(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def span_start(text: str, year: int) -> date | None:
    """
    "2026-09-17(목)~2026-09-19(토) 3일간" 에서 시작일을 뽑는다.

    "9/17(목)~" 처럼 연도가 빠진 표기가 흔하다. 이때는 인자로 받은
    year, 즉 대상일의 연도를 쓴다. 날짜를 찾지 못하면 None 이다.
    """
    m = re.search(r"(?:(\d{4})\s*[-./년]\s*)?(\d{1,2})\s*[-./월]\s*(\d{1,2})", text)
    if not m:
        return None
    try:
        return date(int(m.group(1) or year), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def check(text: str, item: dict, meta: dict, target: date) -> list[str]:
    """협력사에 보내도 되는 문서인지 본다."""
    issues = []

    titles = re.findall(r"^\d+\. (.+)$", text, re.M)
    for s in SECTIONS:
        if s not in titles:
            issues.append(f"'{s}' 절 없음")

    # 홍보는 실행일 전에 한 번은 나가야 한다 (C001·C002).
    # 시점은 "실행 1주 전" 처럼 쓰기도 하고 "2026-09-03" 처럼 쓰기도 한다.
    # 날짜가 있으면 날짜로 보고, 없을 때만 표현으로 본다.
    schedule = item.get("홍보_일정") or []
    if schedule and not any(
            (d < target) if (d := span_start(str(s.get("시점") or ""), target.year))
            else bool(BEFORE_EXEC.search(str(s.get("시점") or "")))
            for s in schedule):
        issues.append("홍보 일정에 실행 전 항목 없음 — "
                      f"{[str(s.get('시점')) for s in schedule]}")

    if proposal_no(meta) not in text:
        issues.append("문서번호 없음")
    if "(서명)" not in text:
        issues.append("서명란 없음")

    for w in INTERNAL:
        if w in text:
            issues.append(f"내부 용어 '{w}' 노출")

    # 실행 예정일과 실행 기간이 같은 문서 안에서 어긋나면 안 된다
    said = field(text, "실행 예정일")
    if said != target.isoformat():
        issues.append(f"실행 예정일이 대상일과 다름 — '{said}' vs {target}")

    span = field(text, "실행 기간")
    if not span or span == "협의 필요":
        issues.append("실행 기간 없음 — 마케터가 정할 값이다")
    else:
        start = span_start(span, target.year)
        if start is None:
            issues.append(f"실행 기간에서 날짜를 읽을 수 없음 — '{span}'")
        elif start != target:
            issues.append(f"실행 기간이 대상일부터 시작하지 않음 — '{span}'")

    # 협력사가 검토할 값이 비어 있으면 협의할 것이 무엇인지 알 수 없다
    if not field(text, "협업 메뉴"):
        issues.append("협업 메뉴 없음")
    deal = item.get("매입") or {}
    if not deal.get("바틀링_제안_매입가"):
        issues.append("제안 매입가 없음")

    return issues


def main() -> None:
    target = datetime.now(KST).date() - timedelta(days=1)
    dow = WEEKDAYS[target.weekday()]
    print("=" * 64)
    print(f"협업 제안서 — 대상일 {target} ({dow})")
    print("=" * 64)

    partner = fetch_partner()
    if not partner:
        print("협력사 없음 — python -m scripts.seed_partner 먼저 실행할 것")
        return

    ctx = build_context(target, partner_category=partner.get("category"))
    result = run(
        context=ctx,
        target_date=target.isoformat(),
        beer_list=build_beer_list(),
        partner_res=build_partner_resources(partner),
        partner_blockers=build_partner_blockers(partner),
        bottling_ingredients=BOTTLING_INGREDIENTS,
        margin_ref=MARGIN_REF,
        weather_pref=WEATHER_PREF,
        trend_menu=NO_TREND_MENU,
        constraints=build_constraints(),
        fewshot="(없음 — 채택 사례가 아직 없다)",
        bottling_sns=BOTTLING_SNS,
        partner_sns=build_partner_sns(partner),
        events=build_events(target),
        past_cases=PAST_CASES,
        rec_reason=NO_REC_REASON,
        on_step=lambda n, label: print(f"  ({n}/4) {label}"),
    )

    if result["error"]:
        print(f"\n체인 실패: {result['error']}")
        return
    print(f"체인 완료 {result['latency_ms']/1000:.1f}초")
    for i in result["issues"]:
        print(f"  [경고] {i}")

    ranked = (result["final"] or {}).get("순위") or []
    if not ranked:
        print("\n순위 없음 — 제안서를 만들 수 없다")
        return
    top = ranked[0]

    # 저장 전에도 문서가 나와야 한다. 번호만 「초안」으로 표시된다
    meta = {"partner_name": partner["name"], "target_date": target.isoformat()}

    missing = missing_fields(top)
    if missing:
        print(f"\n1위 안에 {', '.join(missing)} 없음 — 제안서를 만들 수 없다")
        print(json.dumps(top, ensure_ascii=False, indent=2))
        return

    text = build_proposal(top, meta)
    print("\n" + text + "\n")

    try:
        blob = build_proposal_docx(text, meta)
        print(f"Word {len(blob):,} bytes")
    except Exception as e:
        print(f"Word 생성 실패: {e}")

    issues = check(text, top, meta, target)
    print("-" * 64)
    if issues:
        for i in issues:
            print(f"  · {i}")
    else:
        print("  협력사에 보낼 수 있는 상태")
    print()


if __name__ == "__main__":
    main()
