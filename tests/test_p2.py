"""
(2) 셰프 프롬프트 확인 — T12 검증용

(1)의 실제 출력을 받아 (2)만 이어 실행한다.
체인 전체를 돌리기 전에 메뉴 생성 단계가 제약을 지키는지 본다.

실행: python -m tests.test_p2
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

from chain.gemini import call
from chain.inputs import (KITCHEN, build_beer_list, build_partner_blockers,
                          build_partner_resources, fetch_partner)
from chain.loader import build
from context.builder import build as build_context

KST = timezone(timedelta(hours=9))
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

# constraints.yaml / fewshot.yaml 은 아직 비어 있다.
# 폐기·채택 사례가 없으므로 지어내지 않는다.
NO_CONSTRAINTS = "(없음 — 폐기 사례가 아직 없다)"
NO_FEWSHOT = "(없음 — 채택 사례가 아직 없다)"


def latest_weekday(dow: int) -> date:
    """가장 최근에 지나간 해당 요일. 오늘이 그 요일이면 오늘."""
    today = datetime.now(KST).date()
    return today - timedelta(days=(today.weekday() - dow) % 7)


def parse_beers(text: str) -> dict[str, dict]:
    """
    맥주 라인업 문자열을 다시 구조로 되돌린다.

    프롬프트에 넣은 것과 같은 문자열을 파싱하므로,
    LLM 이 본 것과 검사가 보는 것이 어긋나지 않는다.
    """
    out = {}
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        body = line[2:]
        fixed = "[고정]" in body
        body = body.replace(" [고정]", "").replace(" [교체 가능]", "")
        parts = [p.strip() for p in body.split(" / ")]
        if len(parts) < 2:
            continue
        m = re.match(r"([\d.]+)원/ml", parts[1])
        out[parts[0]] = {
            "price": float(m.group(1)) if m else None,
            "style": parts[2] if len(parts) > 2 else "",
            "alcohol": "논알콜" not in body,
            "fixed": fixed,
        }
    return out


def check(out: dict, beers: dict, partner: dict) -> list[str]:
    """프롬프트가 지시한 제약을 지켰는지 본다."""
    issues = []
    menus = out.get("메뉴안") or []

    if len(menus) != 3:
        issues.append(f"메뉴안 {len(menus)}개 — 3개여야 함")

    ids = [m.get("안_id") for m in menus]
    if len(set(ids)) != len(ids):
        issues.append(f"안_id 중복: {ids}")

    approaches = [m.get("접근") for m in menus]
    if len(set(approaches)) != len(approaches):
        issues.append(f"접근이 중복됨: {approaches}")

    p_ing = set(partner.get("ingredients") or [])
    picked_prices = []

    for m in menus:
        mid = m.get("안_id", "?")

        # 페어링은 라인업 안에서, 알코올 중에서
        pair = (m.get("페어링_맥주") or {}).get("메뉴명")
        if not pair:
            issues.append(f"{mid}: 페어링 맥주 없음")
        elif pair not in beers:
            issues.append(f"{mid}: 라인업에 없는 맥주 '{pair}'")
        else:
            if not beers[pair]["alcohol"]:
                issues.append(f"{mid}: 논알콜 페어링 '{pair}'")
            picked_prices.append(beers[pair]["price"])

        reason = (m.get("페어링_맥주") or {}).get("선정_이유") or ""
        if len(reason) < 15:
            issues.append(f"{mid}: 페어링 이유가 너무 짧음")

        # 협력사 식재료를 최소 1개
        used = {r.get("재료") for r in (m.get("필요_재료") or [])
                if r.get("제공처") == "협력사"}
        if not used:
            issues.append(f"{mid}: 협력사 식재료 미사용")
        elif p_ing and not (used & p_ing):
            issues.append(f"{mid}: 협력사가 없는 재료 {sorted(used - p_ing)}")

        # 원가·판매가
        cost, price = m.get("예상_원가"), m.get("판매가_제안")
        if not price:
            issues.append(f"{mid}: 판매가 미제시 (원가와 별개로 정해야 함)")
        if isinstance(cost, str) and "산출 불가" not in cost:
            n = re.search(r"([\d,]+)", cost)
            if n and price:
                c = int(n.group(1).replace(",", ""))
                if c > price * 0.4:
                    issues.append(f"{mid}: 원가율 {c/price:.0%} (40% 초과)")

        # 누가 어디서 만드는지 밝혔는가
        if not m.get("조리_주체"):
            issues.append(f"{mid}: 조리 주체 미표기")

        # 바틀링이 대는 장비가 실제로 있는가
        for e in m.get("필요_장비") or []:
            if e.get("제공처") != "바틀링":
                continue
            name = str(e.get("장비", ""))
            # 표기가 "A 또는 B" 처럼 올 수 있어 조각으로 대조한다
            frags = re.split(r"\s*(?:또는|/|,)\s*", name)
            if not any(f and f in KITCHEN for f in frags):
                issues.append(f"{mid}: 바틀링에 없는 장비 '{name}'")

        if not m.get("제약_충족_확인"):
            issues.append(f"{mid}: 제약 충족 확인 누락")

    # 세 안이 모두 저가 라인에 몰리지 않아야 한다
    known = [p for p in picked_prices if p is not None]
    if len(known) == 3 and max(known) <= 14:
        issues.append(f"페어링이 모두 저가 라인 {known}")

    return issues


# 메뉴명·구성에 나오면 곤란한 재료.
#
# 협력사·바틀링 어느 목록에도 없는데 등장한 적이 있는 것들이다.
# 실제로 "붕어빵 아이스크림 플레이트"가 나왔으나 아이스크림은
# 어디에도 없었다. 목록을 전부 열거할 수는 없으므로,
# 겪은 것부터 하나씩 쌓는다.
GHOST = ["아이스크림", "생크림", "치즈", "베이컨", "시럽", "잼", "초콜릿"]


def check_ghost(out: dict, partner: dict) -> list[str]:
    """목록에 없는 재료가 메뉴명·구성에 등장하는지 본다."""
    have = " ".join([
        " ".join(partner.get("ingredients") or []),
        KITCHEN,
    ])
    issues = []
    for m in out.get("메뉴안") or []:
        text = f"{m.get('메뉴명', '')} {m.get('구성', '')}"
        for g in GHOST:
            if g in text and g not in have:
                issues.append(f"{m.get('안_id', '?')}: 목록에 없는 재료 '{g}'")
    return issues


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
                      kitchen_constraints=KITCHEN,
                      partner_resources=build_partner_resources(partner),
                      partner_blockers=build_partner_blockers(partner),
                      constraints=NO_CONSTRAINTS,
                      fewshot=NO_FEWSHOT)
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
              f" / 원가 {m.get('예상_원가')} / 판매가 {m.get('판매가_제안')}")

    issues = check(out, beers, partner) + check_ghost(out, partner)
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
