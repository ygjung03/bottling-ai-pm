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
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from chain.gemini import call
from chain.inputs import (BOTTLING_SNS, KITCHEN, NO_REC_REASON,
                          build_beer_list, build_events,
                          build_partner_blockers, build_partner_resources,
                          build_partner_sns, fetch_partner)
from chain.loader import build
from context.builder import build as build_context

KST = timezone(timedelta(hours=9))
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

NO_CONSTRAINTS = "(없음 — 폐기 사례가 아직 없다)"
NO_FEWSHOT = "(없음 — 채택 사례가 아직 없다)"

OUT_DIR = Path("tests/out")

# 1위 안에 반드시 있어야 하는 것.
# 대표가 이 문서만 보고 실행할 수 있어야 한다(명세서 4-2).
REQUIRED = ["메뉴명", "구성", "필요_재료", "조리_주체", "판매가_제안",
            "페어링_맥주", "이벤트", "홍보_문구", "실행_준비물",
            "소요_기간", "추천_근거"]

# 순위를 회피하는 표현.
VAGUE = re.compile(r"우열을? (?:가리기|판단하기) (?:어렵|힘들)"
                   r"|비슷하여 (?:순위|우열)"
                   r"|판단 불가")

# 제외 사유로 쓰이면 안 되는 표현.
#
# 제외는 실행이 불가능할 때만이다(검수 1·2·6번).
# "덜 매력적", "단가가 낮음", "후순위"는 3위 사유이지 제외 사유가 아니다.
# 실제로 매력도와 단가를 근거로 C안을 제외한 적이 있다.
VAGUE_EXCLUDE = re.compile(
    r"매력(?:도|이)|다양성|우위|경쟁력|후순위|밀림|떨어[지짐]|부족"
    r"|기여도 (?:측면|면)")


def parse_beer_prices(text: str) -> dict[str, float]:
    """맥주 라인업 문자열에서 이름과 단가를 뽑는다."""
    out = {}
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        parts = [p.strip() for p in line[2:].split(" / ")]
        if len(parts) < 2:
            continue
        m = re.match(r"([\d.]+)원/ml", parts[1])
        if m:
            out[parts[0]] = float(m.group(1))
    return out


def latest_weekday(dow: int) -> date:
    today = datetime.now(KST).date()
    return today - timedelta(days=(today.weekday() - dow) % 7)


def check(out: dict, p2: dict, beers: dict) -> list[str]:
    """프롬프트가 지시한 제약을 지켰는지 본다."""
    issues = []

    ranks = out.get("순위") or []
    excluded = out.get("제외") or []
    p2_ids = {m.get("안_id") for m in (p2.get("메뉴안") or [])}

    if out.get("재생성_필요"):
        if ranks:
            issues.append("재생성 필요인데 순위가 있음")
        return issues

    if not ranks:
        issues.append("순위 없음")

    # 모든 안이 순위나 제외 중 한쪽에 있어야 한다
    seen = {r.get("안_id") for r in ranks} | {e.get("안_id") for e in excluded}
    missing = p2_ids - seen
    if missing:
        issues.append(f"순위·제외 어디에도 없는 안: {sorted(missing)}")

    # 제외는 실행 불가일 때만이다.
    # 덜 매력적이라거나 단가가 낮다는 것은 3위 사유이지 제외 사유가 아니다.
    for e in excluded:
        why = str(e.get("제외_사유") or "")
        if VAGUE_EXCLUDE.search(why):
            issues.append(f"{e.get('안_id')}: 순위 사유로 제외함 — {why[:40]}")

    # 순위는 1부터 빠짐없이
    nums = sorted(r.get("순위") for r in ranks if r.get("순위"))
    if nums != list(range(1, len(ranks) + 1)):
        issues.append(f"순위 번호 이상: {nums}")

    # 메뉴를 새로 만들지 않았는가
    p2_names = {m.get("메뉴명") for m in (p2.get("메뉴안") or [])}
    for r in ranks:
        if r.get("메뉴명") and r["메뉴명"] not in p2_names:
            issues.append(f"{r.get('안_id')}: (2)에 없는 메뉴명 '{r['메뉴명']}'")

        # 단가를 옮겨 적다 틀리는 일이 있다.
        # 카이저돔 16원을 20원으로, 37디그리스 14원을 8원으로 적은 적이 있다.
        pair = r.get("페어링_맥주") or {}
        name, price = pair.get("메뉴명"), pair.get("원_ml")
        if name and name not in beers:
            issues.append(f"{r.get('안_id')}: 라인업에 없는 맥주 '{name}'")
        elif name and price is not None and float(price) != beers[name]:
            issues.append(f"{r.get('안_id')}: {name} 단가 틀림 "
                          f"({price} → {beers[name]:.0f} 이어야 함)")

    # 1위는 그대로 실행할 수 있어야 한다
    if ranks:
        top = next((r for r in ranks if r.get("순위") == 1), ranks[0])
        for k in REQUIRED:
            v = top.get(k)
            if not v:
                issues.append(f"1위에 '{k}' 없음")

        basis = top.get("추천_근거") or {}
        for k in ("상권_지표", "자원_매칭"):
            if not basis.get(k):
                issues.append(f"1위 추천 근거에 '{k}' 없음")

    # 후순위 사유가 있어야 한다
    for r in ranks:
        if r.get("순위") != 1 and not r.get("선정_사유"):
            issues.append(f"{r.get('안_id')}: 후순위 사유 없음")
        if not (r.get("예상_리스크") or []):
            issues.append(f"{r.get('안_id')}: 예상 리스크 없음")

    for e in excluded:
        if not e.get("제외_사유"):
            issues.append(f"{e.get('안_id')}: 제외 사유 없음")

    # 검수 결과를 남겼는가
    if not (out.get("체크리스트") or []):
        issues.append("체크리스트 없음")

    # 순위를 회피하지 않았는가
    if VAGUE.search(json.dumps(out, ensure_ascii=False)):
        issues.append("순위 판단을 회피하는 표현 사용")

    return issues


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
    try:
        p2, ms["p2"] = call(build(
            "p2_chef",
            p1_output=json.dumps(p1, ensure_ascii=False),
            beer_list=beer_text, kitchen_constraints=KITCHEN,
            partner_resources=build_partner_resources(partner),
            partner_blockers=build_partner_blockers(partner),
            constraints=NO_CONSTRAINTS, fewshot=NO_FEWSHOT))
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
            bottling_sns=BOTTLING_SNS,
            partner_sns=build_partner_sns(partner),
            events=build_events(target)))
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
        beer_list=beer_text,
        rec_reason=NO_REC_REASON,
        constraints=NO_CONSTRAINTS, fewshot=NO_FEWSHOT)
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
