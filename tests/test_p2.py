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
from chain.inputs import (BOTTLING_INGREDIENTS, MARGIN_REF, NO_TREND_MENU,
                          WEATHER_PREF, build_beer_list, build_constraints,
                          build_partner_blockers, build_partner_resources,
                          fetch_partner)
from chain.loader import build
from context.builder import build as build_context

KST = timezone(timedelta(hours=9))
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

# fewshot.yaml 은 아직 비어 있다. 채택 사례가 없으므로 지어내지 않는다.
# constraints 는 8/31 사례에서 뽑은 7건이 들어와 실제 값을 쓴다.
NO_FEWSHOT = "(없음 — 채택 사례가 아직 없다)"

# 완제품 매입 단일화로 사라진 필드 (명세서 1-2).
# 남아 있으면 프롬프트에 옛 지시가 붙어 있다는 뜻이다.
COOKING_FIELDS = ["조리_방법", "조리_주체", "조리_난이도", "필요_장비", "필요_재료"]

# 「접근」은 조리 방식이 아니라 구성과 가격대로 나뉜다.
APPROACHES = {"단품", "세트", "원가 절감형"}


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


def check(out: dict, beers: dict) -> list[str]:
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
    unknown = [a for a in approaches if a not in APPROACHES]
    if unknown:
        issues.append(f"정의에 없는 접근 {unknown} — {sorted(APPROACHES)} 중이어야 함")

    picked_prices = []

    for m in menus:
        mid = m.get("안_id", "?")

        # 조리가 없어졌는데 필드가 남아 있으면 옛 프롬프트다
        left = [k for k in COOKING_FIELDS if m.get(k)]
        if left:
            issues.append(f"{mid}: 사라진 조리 필드가 남아 있음 {left}")

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

        # 누가 무엇을 대는지 나뉘어 있는가.
        # 협력사가 완제품을 내지 않으면 매입할 것이 없어 협업이 아니다.
        if not (m.get("협력사_제공") or []):
            issues.append(f"{mid}: 협력사 제공 품목 없음 — 매입할 것이 없다")
        if not (m.get("바틀링_준비") or []):
            issues.append(f"{mid}: 바틀링 준비 항목 없음")

        # 완제품 조건. 보관 방법과 유통 기한이 기획의 전제다 (C006)
        if not m.get("보관_조건"):
            issues.append(f"{mid}: 보관 조건 없음")
        if not m.get("1회_납품_수량"):
            issues.append(f"{mid}: 1회 납품 수량 없음")

        # 매입가·판매가.
        #
        # 원가율 40% 검사는 뺐다(명세서 5-1). 매입 형태에서 매입가는
        # 협력사와 협의할 값이라 40% 라는 기준에 근거가 없다.
        # 대신 손익 역전만 막는다 (A6).
        cost, price = m.get("협력사희망_매입가"), m.get("판매가_제안")
        if not price:
            issues.append(f"{mid}: 판매가 미제시 (매입가와 별개로 정해야 함)")

        # 무엇에 근거했는지 밝혀야 한다. 마진 기준값 3건에만 기대면
        # 근거가 얇다 — 형태가 다른 값이라 참고 이상이 못 된다 (U18).
        basis = str(m.get("판매가_근거") or "")
        if not basis:
            issues.append(f"{mid}: 판매가 근거 없음")
        elif not re.search(r"\d", basis):
            issues.append(f"{mid}: 판매가 근거에 수치가 없음 — {basis[:40]}")
        if isinstance(cost, str) and "산출 불가" not in cost:
            n = re.search(r"([\d,]+)", cost)
            if n and price:
                c = int(n.group(1).replace(",", ""))
                if c >= price:
                    issues.append(f"{mid}: 매입가 {c:,}원 ≥ 판매가 {price:,}원"
                                  f" — 손익 역전")

        # 협력사 매장에서 사는 값. 매입가를 제안할 때 이것과 견준다.
        if not m.get("협력사_정가"):
            issues.append(f"{mid}: 협력사 정가 없음 — 매입가를 견줄 기준이 없다")

        # 맥주값을 넣는 것은 세트뿐이다.
        #
        # 셀프탭이라 손님이 300ml 만 마실 수도 1L 를 마실 수도 있어, 맥주를
        # 늘 500ml 로 묶으면 그 방식이 깨진다. 예전에 이 구분이 없어서
        # 판매가가 어떤 때는 안주 값이고 어떤 때는 맥주 포함 값이었고,
        # 화면이 늘 안주 값으로 보고 맥주를 한 번 더 더했다.
        listed = m.get("정가_합")
        is_set = m.get("접근") == "세트"

        if is_set and not listed:
            issues.append(f"{mid}: 세트인데 정가 합이 없음")
        if not is_set and listed:
            issues.append(f"{mid}: 세트가 아닌데 정가 합이 있음 ({listed:,}원)"
                          f" — 맥주는 별개 거래다")

        # 세트는 따로 사는 것보다 싸야 한다. 값이 같으면 묶을 이유가 없다.
        if is_set and listed and price:
            if price >= listed:
                issues.append(f"{mid}: 세트가 {price:,}원 ≥ 정가 합 "
                              f"{listed:,}원 — 할인이 없다")

        # 이미지는 이 단계 다음에 별도로 생성된다 (명세서 1-2 ④)
        if m.get("메뉴_이미지"):
            issues.append(f"{mid}: 메뉴 이미지를 지어냄 — 별도 단계에서 생성한다")

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
    """
    메뉴명·구성에 나온 재료가 어디서 오는지 본다 (프롬프트 규칙 8).

    올 곳은 둘뿐이다 — 협력사가 납품하는 메뉴, 그리고 바틀링이 준비하는 것.
    둘 다 아니면 아무도 준비하지 않는 재료라 그 안은 실행되지 않는다.
    """
    sold = " ".join(str(m.get("메뉴") or "")
                    for m in (partner.get("menu_prices") or []))
    base = f"{sold} {partner.get('signature_menu') or ''}"

    issues = []
    for m in out.get("메뉴안") or []:
        text = f"{m.get('메뉴명', '')} {m.get('구성', '')}"
        prep = " ".join(str(x) for x in (m.get("바틀링_준비") or []))
        have = f"{base} {prep}"
        for g in GHOST:
            if g in text and g not in have:
                issues.append(f"{m.get('안_id', '?')}: '{g}' 가 어디서 오는지 "
                              f"없음 — 바틀링_준비에 적혀야 한다")
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
                      partner_resources=build_partner_resources(partner),
                      partner_blockers=build_partner_blockers(partner),
                      bottling_ingredients=BOTTLING_INGREDIENTS,
                      margin_ref=MARGIN_REF,
                      weather_pref=WEATHER_PREF,
                      trend_menu=NO_TREND_MENU,
                      constraints=build_constraints()["p2"],
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
              f" / 매입 {m.get('협력사희망_매입가')}"
              f" / 정가합 {m.get('정가_합')} / 판매가 {m.get('판매가_제안')}")
        print(f"      보관 {m.get('보관_조건')} / 납품 {m.get('1회_납품_수량')}")

    issues = check(out, beers) + check_ghost(out, partner)
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
