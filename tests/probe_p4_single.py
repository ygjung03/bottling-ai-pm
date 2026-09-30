"""
확인용: (4)에게 안을 하나만 주면 제안서 필드가 다 채워지는가.

2차는 안이 확정된 상태다(쟁점_2차흐름과_폼_0925.md 1-1-2). 지금 (4) 프롬프트는
「세 안」을 전제로 쓰여 있어(10~11·55~56·136·194·266행) 안 하나로도 돌아가는지
실제로 봐야 한다.

저장된 3안 결과에서 안 하나만 남겨 (4)를 다시 부른다. LLM 호출은 안당 1회다.

  python -m tests.probe_p4_single              A안으로 1회
  python -m tests.probe_p4_single --id B       B안으로
  python -m tests.probe_p4_single --times 3    같은 입력으로 3회 (흔들림 확인)
"""
import json
import sys
from datetime import date

from chain.checks import check_final, parse_beer_prices
from chain.gemini import call
from chain.inputs import (NO_REC_REASON, build_beer_list, build_constraints,
                          build_events, build_partner_resources, fetch_partner)
from chain.loader import build
from chain.runner import NO_ISSUES
from app.proposal import REQUIRED, missing_fields

SRC = "tests/results_34ad77a.json"
RUN = 1          # C1 — 3안 완주한 회차

# 제안서가 안 하나에서 읽는 값. app/proposal.py 를 훑어 모은 것이다.
# REQUIRED 는 없으면 문서를 아예 만들지 않는 것이고, 이쪽은 비면 그 줄이
# "협의 필요"·"데이터 없음"으로 나가는 것까지 포함한다.
USED = ["안_id", "접근", "메뉴명", "구성", "페어링_맥주", "판매가_제안", "정가_합",
        "판매가_설명", "배경", "이벤트", "홍보_일정", "홍보_문구",
        "협력사_제공", "바틀링_준비", "역할분담", "상호_이익", "매입",
        "보관_조건", "1회_납품_수량", "납품_일시", "선정_사유"]


def one(p1: dict, p2: dict, p3: dict, aid: str, partner: dict,
        target: date, n: int) -> None:
    menus = [m for m in p2["메뉴안"] if m.get("안_id") == aid]
    if not menus:
        raise SystemExit(f"{aid} 안이 없다 — "
                         f"{[m.get('안_id') for m in p2['메뉴안']]}")
    plans = [x for x in p3["안별_기획"] if x.get("안_id") == aid]

    p2_one = {**p2, "메뉴안": menus}
    p3_one = {**p3, "안별_기획": plans}

    beer_text = build_beer_list()
    prompt = build(
        "p4_consultant",
        p1_output=json.dumps(p1, ensure_ascii=False),
        p2_output=json.dumps(p2_one, ensure_ascii=False),
        p3_output=json.dumps(p3_one, ensure_ascii=False),
        events=build_events(target),
        beer_list=beer_text,
        partner_resources=build_partner_resources(partner),
        rec_reason=NO_REC_REASON,
        constraints=build_constraints()["p4"],
        fewshot="(없음 — 채택 사례가 아직 없다)",
        prev_output=NO_ISSUES,
        issues=NO_ISSUES,
    )

    out, ms = call(prompt)
    items = out.get("안") or []
    print(f"\n--- {n}회 / {aid}안 / {ms:,}ms / 안 {len(items)}개 "
          f"/ 제외 {len(out.get('제외') or [])}건 "
          f"/ 재생성_필요 {out.get('재생성_필요')}")

    if not items:
        print("  안이 비어서 나왔다. 제외 사유:")
        for x in out.get("제외") or []:
            print(f"    {x.get('안_id')}: {str(x.get('사유'))[:120]}")
        return

    it = items[0]
    miss = missing_fields(it)
    print(f"  REQUIRED {list(REQUIRED)} → "
          f"{'전부 있음' if not miss else f'빈 것 {miss}'}")

    empty = [k for k in USED if not it.get(k)]
    print(f"  제안서가 쓰는 {len(USED)}개 중 빈 것 {len(empty)}개"
          f"{': ' + str(empty) if empty else ''}")

    chk = check_final(out, p2_one, parse_beer_prices(beer_text))
    print(f"  check_final → redo {len(chk.redo)}건 / warn {len(chk.warn)}건")
    for x in chk.redo:
        print(f"    [redo] {x[:150]}")
    for x in chk.warn:
        print(f"    [warn] {x[:150]}")


def main() -> None:
    argv = sys.argv[1:]
    aid = argv[argv.index("--id") + 1] if "--id" in argv else "A"
    times = int(argv[argv.index("--times") + 1]) if "--times" in argv else 1

    d = json.load(open(SRC, encoding="utf-8"))
    run = d["runs"][RUN]
    o = run["output"]
    print(f"입력  {SRC} runs[{RUN}] {run['case_id']} "
          f"— 원래 안 {len(o['p2']['메뉴안'])}개 "
          f"{[m.get('안_id') for m in o['p2']['메뉴안']]}")

    partner = fetch_partner()
    if not partner:
        raise SystemExit("협력사 없음 — python -m scripts.seed_partner")
    target = date.fromisoformat(run.get("target_date") or "2026-10-09")

    for n in range(1, times + 1):
        one(o["p1"], o["p2"], o["p3"], aid, partner, target, n)


if __name__ == "__main__":
    main()
