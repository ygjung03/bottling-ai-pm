"""
(3) 마케터 프롬프트 확인 — T12 검증용

(1)→(2)→(3)을 실제로 이어 돌린다.
가짜 입력을 만들면 실제 형식과 어긋나므로 앞 단계를 그대로 쓴다.

실행: python -m tests.test_p3
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

from chain.gemini import call
from chain.inputs import (BOTTLING_INGREDIENTS, BOTTLING_SNS, MARGIN_REF,
                          NO_DATA, NO_TREND_MENU, PAST_CASES, WEATHER_PREF,
                          build_beer_list, build_constraints, build_events,
                          build_partner_blockers, build_partner_resources,
                          build_partner_sns, fetch_partner)
from chain.loader import build
from context.builder import build as build_context

KST = timezone(timedelta(hours=9))
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

NO_FEWSHOT = "(없음 — 채택 사례가 아직 없다)"

# 도달·노출 목표에 쓰이는 수치 표현.
#
# 이런 값을 우리가 측정하지 않으므로 목표로 쓸 수 없다. 달성했는지
# 확인할 방법이 없다. 목표는 팔린 수량으로 쓴다 (프롬프트 규칙 3).
#
# 어순이 양쪽으로 나타난다. "도달 10,000명"도 "10,000명 도달"도 쓰인다.
KEYWORD = r"도달|노출|조회|좋아요|팔로워|저장|공유|유입|방문자"
REACH = re.compile(
    rf"(?:{KEYWORD})\s*\d[\d,]*"      # 도달 10,000
    rf"|\d[\d,]*\s*[명회건%]?\s*(?:{KEYWORD})"   # 10,000명 도달
)

# 문구가 아니라 문구에 대한 설명일 때 나타나는 표현.
# "~를 강조하는 문구" 같은 것은 그대로 게시할 수 없다.
NOT_A_COPY = re.compile(r"(?:하는|강조|어필|소구|담은|활용한|중심의)\s*"
                        r"(?:문구|카피|메시지|내용)")

# 타겟이 사람이 아니라 통계일 때 나타나는 형태.
# "20대 21% / 40대 18%" 처럼 비중을 옮겨 적으면 홍보 대상이 아니다.
STAT_TARGET = re.compile(r"\d+대\s*\d+%.*?\d+대\s*\d+%")

# 준비물에 들어오면 안 되는 것 — 조리·보관 장비.
# 협업이 완제품 매입 하나이므로 바틀링은 조리하지 않는다.
# (3)의 준비물은 홍보·이벤트 실행에 새로 챙길 것
# (포장재·홍보물·촬영 소품 등)이어야 한다.
OWNED = ["냉장고", "냉동", "전자레인지", "화덕", "오븐", "그릴",
         "어묵중탕기", "착즙기", "셀프탭", "디스펜서", "소도구"]

# 장비 이름이 들어 있어도 인쇄물이면 준비물로 맞다.
# "셀프탭 맥주 제공 환경 확인용 안내물"을 장비로 잡은 적이 있다 —
# 장비가 아니라 그 장비를 설명하는 인쇄물이다.
PROMO_ITEM = re.compile(r"안내물|안내판|포스터|홍보물|게시물|전단|스티커"
                        r"|배너|현수막|메뉴판|쿠폰|카드")

# 홍보 일정의 "실행 전" 시점. C001·C002 의 자동 검사다 (명세서 5-1 A7).
# 실행 기간에만 알리면 사람들이 알기 전에 끝난다 — 카페 협업이 그랬다.
BEFORE_EXEC = re.compile(r"전|예고|티저|D-\s*\d")

# 실행 기간을 며칠로 잡았는지. C003 의 자동 검사다 (A8).
MIN_DAYS = 3


def duration_days(text: str) -> int | None:
    """
    "9/5(금)～9/7(일) 3일간" 같은 표기에서 일수를 뽑는다.

    "3일간"이 있으면 그대로 쓰고, 없으면 날짜 범위로 센다.
    둘 다 없으면 None — 판정하지 않는다. 근거 없이 위반으로 몰지 않는다.
    """
    named = re.findall(r"(\d+)\s*일간?", text)
    if named:
        return max(int(x) for x in named)

    md = re.findall(r"(\d{1,2})/(\d{1,2})", text)
    if len(md) >= 2:
        try:
            a = date(2026, int(md[0][0]), int(md[0][1]))
            b = date(2026, int(md[-1][0]), int(md[-1][1]))
        except ValueError:
            return None
        return (b - a).days + 1 if b >= a else None
    return None


def span_start(text: str, year: int) -> date | None:
    """
    "2026-09-17(목)~2026-09-19(토) 3일간" 같은 표기에서 시작일을 뽑는다.

    "9/17(목)~" 처럼 연도가 빠진 표기가 흔하다. 이때는 인자로 받은
    year, 즉 대상일의 연도를 쓴다.

    날짜를 찾지 못하면 None 을 돌려준다. "3일간"처럼 일수만 적힌 경우가
    여기 해당하며, 근거가 없으므로 위반으로 몰지 않는다.
    """
    m = re.search(r"(?:(\d{4})\s*[-./년]\s*)?(\d{1,2})\s*[-./월]\s*(\d{1,2})", text)
    if not m:
        return None
    try:
        return date(int(m.group(1) or year), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def latest_weekday(dow: int) -> date:
    today = datetime.now(KST).date()
    return today - timedelta(days=(today.weekday() - dow) % 7)


def check(out: dict, p2: dict, target: date,
          partner_sns: bool = True) -> list[str]:
    """
    프롬프트가 지시한 제약을 지켰는지 본다.

    partner_sns: 협력사가 SNS 를 운영하는가.
      없으면 협력사에 홍보를 요청하지 않는 것이 맞다 (규칙 10).
      판매가 바틀링 매장에서 이뤄지므로 협력사 매장 게시물로 얻는 것이
      불확실하고, 없는 채널을 대신할 것을 만들면 부담만 늘어난다.
    """
    issues = []

    axis = out.get("공통_홍보축") or {}
    if not axis:
        issues.append("공통 홍보축 없음")
    else:
        for k in ("타겟", "공략_시점", "채널별_전략"):
            if not axis.get(k):
                issues.append(f"공통 홍보축에 '{k}' 없음")

        # 타겟은 사람이어야 한다. 비중 나열은 홍보 대상이 아니다.
        tgt = str(axis.get("타겟") or "")
        if STAT_TARGET.search(tgt):
            issues.append(f"타겟이 통계 나열임 — {tgt[:40]}")

        # A7 — 홍보 일정에 실행 전 항목이 하나 이상 (C001·C002)
        schedule = axis.get("홍보_일정") or []
        if not schedule:
            issues.append("홍보 일정 없음 — 언제 무엇을 올리는지가 있어야 한다")
        else:
            for s in schedule:
                for k in ("시점", "채널", "내용"):
                    if not s.get(k):
                        issues.append(f"홍보 일정 항목에 '{k}' 없음: {s}")
            # 시점은 "실행 1주 전" 같은 상대 표현으로도, "2026-09-03" 같은
            # 실제 날짜로도 온다. 실행일을 알려준 뒤로는 날짜 쪽이 많다.
            #
            # 날짜가 적혀 있으면 그것으로 판정한다. 실행일 당일이나 그 뒤는
            # 사전 홍보가 아니다. 날짜가 없을 때만 표현을 본다.
            def is_before(s) -> bool:
                when = str(s.get("시점") or "")
                day = span_start(when, target.year)
                if day:
                    return day < target
                return bool(BEFORE_EXEC.search(when))

            if not any(is_before(s) for s in schedule):
                when = [str(s.get("시점")) for s in schedule]
                issues.append(f"홍보 일정에 '실행 전' 항목 없음 — {when}")

        # A9 — 채널별 전략에 협력사 주체가 하나 이상
        channels = axis.get("채널별_전략") or []
        for c in channels:
            if not c.get("주체"):
                issues.append(f"채널별 전략에 '주체' 없음: {c}")
        has_partner = any(c.get("주체") == "협력사" for c in channels)
        if partner_sns and not has_partner:
            issues.append("채널별 전략에 협력사 주체 없음 — "
                          "함께 올리면 같은 노력으로 두 배가 닿는다")
        if not partner_sns and has_partner:
            issues.append("협력사에 SNS 가 없는데 협력사 주체 항목을 넣었다")

    plans = out.get("안별_기획") or []
    p2_ids = [m.get("안_id") for m in (p2.get("메뉴안") or [])]
    p3_ids = [p.get("안_id") for p in plans]

    if len(plans) != len(p2_ids):
        issues.append(f"안별 기획 {len(plans)}개 — 메뉴안 {len(p2_ids)}개와 불일치")
    if set(p3_ids) != set(p2_ids):
        issues.append(f"안_id 불일치: (2){p2_ids} vs (3){p3_ids}")

    goal = str(axis.get("목표") or "")
    if REACH.search(goal):
        issues.append(f"측정하지 않는 값을 목표로 삼음: {goal[:40]}")

    for p in plans:
        pid = p.get("안_id", "?")

        ev = p.get("이벤트안") or {}
        for k in ("명칭", "내용", "기간"):
            v = ev.get(k)
            if not v:
                issues.append(f"{pid}: 이벤트안에 '{k}' 없음")
            elif NO_DATA in str(v):
                issues.append(f"{pid}: 이벤트안 '{k}'가 데이터 없음 — 마케터가 정할 값이다")

        # A8 — 실행 기간 3일 이상 (C003)
        span = str(ev.get("기간") or "")
        days = duration_days(span)
        if days is not None and days < MIN_DAYS:
            issues.append(f"{pid}: 실행 기간 {days}일 — {MIN_DAYS}일 이상이어야 함")

        # 기간이 실행 예정일부터 시작하는가.
        #
        # (3)이 실행일을 몰라 스키마 예시를 그대로 베끼거나 엉뚱한 달을
        # 지어낸 적이 있다. 이 값은 제안서에 그대로 실려 협력사에 나간다.
        start = span_start(span, target.year)
        if start and start != target:
            issues.append(f"{pid}: 실행 기간이 대상일부터 시작하지 않음 "
                          f"— 대상 {target} / 기간 '{span}'")

        copy = str(p.get("홍보_문구") or "")
        if not copy:
            issues.append(f"{pid}: 홍보 문구 없음")
        elif NOT_A_COPY.search(copy):
            issues.append(f"{pid}: 문구가 아니라 설명임 — {copy[:30]}")
        elif len(copy) < 15:
            issues.append(f"{pid}: 홍보 문구가 너무 짧음")

        tags = p.get("해시태그") or []
        if not tags:
            issues.append(f"{pid}: 해시태그 없음")
        elif any(not str(t).startswith("#") for t in tags):
            issues.append(f"{pid}: '#' 없는 해시태그 {tags}")

        for k in ("차별_포인트", "준비물", "소요_기간"):
            v = p.get(k)
            if not v:
                issues.append(f"{pid}: '{k}' 없음")
            elif NO_DATA in str(v):
                issues.append(f"{pid}: '{k}'가 데이터 없음 — 마케터가 정할 값이다")

        # 준비물은 홍보·이벤트용이어야 한다. 조리 장비는 (2)의 몫이다.
        for item in p.get("준비물") or []:
            if PROMO_ITEM.search(str(item)):
                continue
            hit = next((o for o in OWNED if o in str(item)), None)
            if hit:
                issues.append(f"{pid}: 조리 장비를 준비물로 적음 — '{item}'")

    # 우열을 매기지 않아야 한다
    text = json.dumps(out, ensure_ascii=False)
    for w in ("1순위", "2순위", "3순위", "가장 추천", "최우선", "베스트"):
        if w in text:
            issues.append(f"우열 표현 '{w}' 사용")

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
            constraints=rules["p2"], fewshot=NO_FEWSHOT))
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
        constraints=rules["p3"], past_cases=PAST_CASES)
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

    issues = check(out, p2, target)
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
