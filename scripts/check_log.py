"""
자동 검사 기록 보기 — 만든 사람이 읽는다

기획안을 만들 때 걸린 것, 되감은 것, 되감고도 남은 것은 화면에 띄우지
않는다. "A: '협력사_정가' 없음" 같은 말은 대표님께 뜻이 없고, 노란
상자로 수십 개가 쌓이면 정작 봐야 할 기획안을 가린다.

대신 plans.auto_check 에 그대로 쌓아 두고 여기서 본다.
프롬프트를 손볼 때(T18) 무엇이 자주 걸리는지가 그 작업 목록이 된다.

실행
  python -m scripts.check_log            최근 10건
  python -m scripts.check_log 30         최근 30건
  python -m scripts.check_log --full     되감기 쪽지 전문까지
"""
import sys
from collections import Counter

from db.client import get_client


def load(limit: int) -> list[dict]:
    return (get_client().table("plans")
            .select("id, created_at, partner_id, target_date, "
                    "auto_check, latency_ms, prompt_version")
            .order("id", desc=True).limit(limit).execute().data or [])


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--full"]
    full = "--full" in sys.argv
    limit = int(args[0]) if args else 10

    rows = load(limit)
    if not rows:
        print("기획안 기록이 없다.")
        return

    counter: Counter = Counter()

    for r in rows:
        check = r.get("auto_check") or {}
        issues = check.get("issues") or []
        rewinds = check.get("rewinds") or []
        restarts = check.get("restarts") or []
        sec = (r.get("latency_ms") or 0) / 1000

        print("=" * 68)
        print(f"#{r['id']}  대상일 {r.get('target_date')}  "
              f"{sec:.1f}초  프롬프트 {r.get('prompt_version') or '?'}")
        print(f"  생성 {r.get('created_at')}")

        # (4) 재호출로 고친 것. 여기 자주 나오는 항목이 프롬프트 후보다
        if rewinds:
            n = sum(len(x) for x in rewinds)
            print(f"  (4) 재호출 {len(rewinds)}회 — {n}건 보완")
            for i, found in enumerate(rewinds, 1):
                for x in found:
                    print(f"      {i}회차 {x}")

        # (2)까지 되감은 것. 쪽지가 길어 기본은 줄 수만 센다
        if restarts:
            print(f"  (2) 되감기 {len(restarts)}회")
            if full:
                for note in restarts:
                    print("      " + note.replace("\n", "\n      "))

        if issues:
            print(f"  남은 것 {len(issues)}건")
            for x in issues:
                print(f"      {x}")
                counter[x.split(" — ")[0]] += 1
        elif not rewinds and not restarts:
            print("  걸린 것 없음")

    if counter:
        print()
        print("=" * 68)
        print(f"자주 걸린 것 (최근 {len(rows)}건)")
        print("=" * 68)
        for what, n in counter.most_common(15):
            print(f"  {n:>3}회  {what}")


if __name__ == "__main__":
    main()
