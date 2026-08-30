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
from chain.inputs import (BOTTLING_SNS, KITCHEN, NO_DATA, build_beer_list,
                          build_events, build_partner_blockers,
                          build_partner_resources, build_partner_sns,
                          fetch_partner)
from chain.loader import build
from context.builder import build as build_context

KST = timezone(timedelta(hours=9))
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

NO_CONSTRAINTS = "(없음 — 폐기 사례가 아직 없다)"
NO_FEWSHOT = "(없음 — 채택 사례가 아직 없다)"

# 도달·노출 목표에 쓰이는 수치 표현.
# 팔로워 규모를 모르는 채널에 이런 목표를 세우면 근거가 없다.
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

# 준비물에 들어오면 안 되는 것 — 조리 장비.
# 그것은 (2)의 "필요_장비"가 다룬다. (3)의 준비물은 홍보·이벤트 실행에
# 새로 챙길 것(포장재·홍보물·촬영 소품 등)이어야 한다.
OWNED = ["냉장고", "냉동", "전자레인지", "화덕", "오븐", "그릴",
         "어묵중탕기", "착즙기", "셀프탭", "디스펜서", "소도구"]


def latest_weekday(dow: int) -> date:
    today = datetime.now(KST).date()
    return today - timedelta(days=(today.weekday() - dow) % 7)


def check(out: dict, p2: dict, sns_known: bool) -> list[str]:
    """프롬프트가 지시한 제약을 지켰는지 본다."""
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

    plans = out.get("안별_기획") or []
    p2_ids = [m.get("안_id") for m in (p2.get("메뉴안") or [])]
    p3_ids = [p.get("안_id") for p in plans]

    if len(plans) != len(p2_ids):
        issues.append(f"안별 기획 {len(plans)}개 — 메뉴안 {len(p2_ids)}개와 불일치")
    if set(p3_ids) != set(p2_ids):
        issues.append(f"안_id 불일치: (2){p2_ids} vs (3){p3_ids}")

    # SNS 규모를 모르면 수치 목표를 세울 수 없다
    if not sns_known:
        goal = str(axis.get("목표") or "")
        if REACH.search(goal):
            issues.append(f"근거 없는 수치 목표: {goal[:40]}")

    for p in plans:
        pid = p.get("안_id", "?")

        ev = p.get("이벤트안") or {}
        for k in ("명칭", "내용", "기간"):
            v = ev.get(k)
            if not v:
                issues.append(f"{pid}: 이벤트안에 '{k}' 없음")
            elif NO_DATA in str(v):
                issues.append(f"{pid}: 이벤트안 '{k}'가 데이터 없음 — 마케터가 정할 값이다")

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
    ctx = build_context(target)
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
    try:
        p2, ms2 = call(build(
            "p2_chef",
            p1_output=json.dumps(p1, ensure_ascii=False),
            beer_list=beer_text, kitchen_constraints=KITCHEN,
            partner_resources=build_partner_resources(partner),
            partner_blockers=build_partner_blockers(partner),
            constraints=NO_CONSTRAINTS, fewshot=NO_FEWSHOT))
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
        bottling_sns=BOTTLING_SNS,
        partner_sns=build_partner_sns(partner),
        events=build_events(target))
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
    for p in out.get("안별_기획") or []:
        name = next((m.get("메뉴명") for m in menus
                     if m.get("안_id") == p.get("안_id")), "?")
        print(f"\n  {p.get('안_id')}. {name}")
        print(f"      {(p.get('이벤트안') or {}).get('명칭')}")
        print(f"      \"{p.get('홍보_문구')}\"")
        print(f"      {' '.join(p.get('해시태그') or [])}")

    issues = check(out, p2, sns_known)
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
