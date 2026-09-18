"""
고정 테스트셋 실행 — T14 (명세서 5-5)

프롬프트를 고치기 전후를 같은 입력으로 비교한다. 케이스는
tests/fixtures/testset.json 에 있다 (협력사 4종 × 1차/2차 = 8건).

[입력을 파일에 박아 둔다]
  컨텍스트 빌더는 지금부터 4주 전까지의 상권 데이터를 읽으므로 내일 돌리면
  값이 달라진다. 프롬프트 v1 과 v2 를 비교할 때 데이터 변화가 섞이면 무엇이
  결과를 바꿨는지 알 수 없다. 그래서 컨텍스트·맥주·행사·제약을 한 번 만들어
  snapshot.json 에 두고, 실행은 그 파일만 읽는다.

[버전은 prompts/ 내용 해시]
  git 해시(HEAD:prompts)는 커밋 전에는 안 바뀐다. 튜닝 중엔 고치고 돌리기를
  반복하므로 파일 내용으로 만든다. 결과는 tests/results_{버전}.json 에 쌓인다.
  같은 케이스를 여러 번 돌려도 전부 남긴다 — LLM 출력은 흔들리므로 한 번으로
  판단하지 않는다.

실행
  python -m tests.test_fixed --snapshot          입력 스냅샷 생성 (처음 한 번, 또는 갱신할 때)
  python -m tests.test_fixed --run               8건 전부
  python -m tests.test_fixed --run C1 C4         일부만
  python -m tests.test_fixed --report            최신 버전 결과 집계
  python -m tests.test_fixed --report tests/results_abc1234.json
"""
import argparse
import hashlib
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from chain.inputs import (BOTTLING_INGREDIENTS, BOTTLING_SNS, MARGIN_REF,
                          NO_REC_REASON, NO_TREND_MENU, PAST_CASES,
                          WEATHER_PREF, build_beer_list, build_constraints,
                          build_events, build_partner_blockers,
                          build_partner_resources, build_partner_sns)
from chain import gemini
from chain.runner import run
from context.builder import build as build_context

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TESTSET = FIXTURES / "testset.json"
SNAPSHOT = FIXTURES / "snapshot.json"
PROMPTS = ROOT / "prompts"

KST = timezone(timedelta(hours=9))
NO_FEWSHOT = "(없음 — 채택 사례가 아직 없다)"

# 채점 기준 초안 ④ — 16원/ml 이상을 고가 라인으로 본다. 저가 쏠림을 세는 기준.
HIGH_PRICE_PER_ML = 16

# 유료 등급 단가 (ai.google.dev/gemini-api/docs/pricing, 2026-09-18, gemini-3.5-flash-lite).
# 무료 키로 돌리면 실제론 0원이지만 대표님 키(유료)로 돌리면 얼마인지를 본다.
USD_PER_M_INPUT = 0.30
USD_PER_M_OUTPUT = 2.50
KRW_PER_USD = 1400   # 환산용 가정. 정확한 환율이 아니다


def cost_usd(tokens_in: int, tokens_out: int) -> float:
    return tokens_in / 1e6 * USD_PER_M_INPUT + tokens_out / 1e6 * USD_PER_M_OUTPUT


def prompt_version() -> str:
    h = hashlib.sha1()
    for p in sorted(PROMPTS.glob("*.yaml")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:7]


def load_testset() -> dict:
    return json.loads(TESTSET.read_text(encoding="utf-8"))


# ══════════════════════════════════════════
# 스냅샷
# ══════════════════════════════════════════

def make_snapshot() -> None:
    ts = load_testset()
    target = date.fromisoformat(ts["target_date"])
    categories = sorted({c["partner"]["category"] for c in ts["cases"]})

    print(f"대상일 {target} / 업종 {categories}")
    contexts = {}
    for cat in categories:
        print(f"  컨텍스트 — {cat}")
        contexts[cat] = build_context(target, partner_category=cat)

    snap = {
        "built_at": datetime.now(KST).isoformat(timespec="seconds"),
        "target_date": target.isoformat(),
        "contexts": contexts,
        "beer_list": build_beer_list(),
        "events": build_events(target),
        "constraints": build_constraints(),
    }
    SNAPSHOT.write_text(json.dumps(snap, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"저장 → {SNAPSHOT.relative_to(ROOT)}")
    for cat, ctx in contexts.items():
        print(f"  {cat:12} {len(ctx):>6}자")


def load_snapshot() -> dict:
    if not SNAPSHOT.exists():
        print("snapshot.json 이 없다. 먼저 --snapshot 을 돌릴 것.")
        raise SystemExit(1)
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


# ══════════════════════════════════════════
# 실행
# ══════════════════════════════════════════

def summarize(r: dict) -> dict:
    """결과에서 비교에 쓸 것만 뽑는다. 원문은 output 에 따로 남긴다."""
    menus = (r["p2"] or {}).get("메뉴안") or []
    final = r["final"] or {}
    ranks = sorted(final.get("순위") or [], key=lambda x: x.get("순위") or 99)
    excluded = final.get("제외") or []

    beers = []
    for rk in ranks:
        b = rk.get("페어링_맥주") or {}
        beers.append({"순위": rk.get("순위"), "메뉴명": rk.get("메뉴명"),
                      "맥주": b.get("메뉴명"), "원_ml": b.get("원_ml")})
    low = [b for b in beers if b["원_ml"] is not None
           and b["원_ml"] < HIGH_PRICE_PER_ML]

    return {
        "error": r["error"],
        "menus": [m.get("메뉴명") for m in menus],
        "ranks": beers,
        "excluded": [{"안_id": e.get("안_id"), "사유": e.get("제외_사유")}
                     for e in excluded],
        "low_price_pairings": len(low),
        "issues": r["issues"],
        "n_rewinds": len(r["rewinds"]),
        "n_restarts": len(r["restarts"]),
        "latency_ms": r["latency_ms"],
    }


def run_cases(ids: list[str] | None) -> None:
    ts = load_testset()
    snap = load_snapshot()
    version = prompt_version()
    out_path = ROOT / "tests" / f"results_{version}.json"

    cases = ts["cases"]
    if ids:
        cases = [c for c in cases if c["id"] in ids]
        missing = set(ids) - {c["id"] for c in cases}
        if missing:
            print(f"없는 케이스: {sorted(missing)}")
            raise SystemExit(1)

    print(f"프롬프트 버전 {version} / 스냅샷 {snap['built_at']} / {len(cases)}건")
    print(f"결과 → {out_path.relative_to(ROOT)}\n")

    results = {"prompt_version": version, "snapshot_built_at": snap["built_at"],
               "runs": []}
    if out_path.exists():
        results = json.loads(out_path.read_text(encoding="utf-8"))

    for c in cases:
        partner = c["partner"]
        cat = partner["category"]
        print(f"[{c['id']}] {partner['name']} · {c['round']}차")

        args = dict(
            context=snap["contexts"][cat],
            target_date=snap["target_date"],
            beer_list=snap["beer_list"],
            partner_res=build_partner_resources(partner),
            partner_blockers=build_partner_blockers(partner),
            bottling_ingredients=BOTTLING_INGREDIENTS,
            margin_ref=MARGIN_REF,
            weather_pref=WEATHER_PREF,
            trend_menu=NO_TREND_MENU,
            constraints=snap["constraints"],
            fewshot=NO_FEWSHOT,
            bottling_sns=BOTTLING_SNS,
            partner_sns=build_partner_sns(partner),
            events=snap["events"],
            past_cases=PAST_CASES,
            rec_reason=NO_REC_REASON,
            partner=partner,
            on_step=lambda n, label: print(f"    ({n}) {label}"),
        )

        gemini.reset_usage()
        t0 = time.perf_counter()
        r = run(**args)
        sec = time.perf_counter() - t0
        s = summarize(r)
        u = dict(gemini.USAGE)
        s["calls"] = u["calls"]
        s["tokens_in"] = u["input_tokens"]
        s["tokens_out"] = u["output_tokens"]
        s["cost_usd"] = round(cost_usd(u["input_tokens"], u["output_tokens"]), 4)

        results["runs"].append({
            "run_at": datetime.now(KST).isoformat(timespec="seconds"),
            "case_id": c["id"], "round": c["round"],
            "summary": s,
            "output": {k: r[k] for k in ("p1", "p2", "p3", "final",
                                          "issues", "rewinds", "restarts", "error")},
        })
        # 케이스마다 바로 쓴다. 중간에 죽어도 앞 것은 남는다.
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                            encoding="utf-8")

        print(f"    {sec:.0f}초 · 메뉴 {len(s['menus'])} · 순위 {len(s['ranks'])}"
              f" · 제외 {len(s['excluded'])} · 저가 페어링 {s['low_price_pairings']}"
              f" · 재호출 {s['n_rewinds']} · 되감기 {s['n_restarts']}"
              f" · 호출 {s['calls']}회 {s['tokens_in']:,}/{s['tokens_out']:,} 토큰"
              f" ≈ ${s['cost_usd']:.3f} ({s['cost_usd'] * KRW_PER_USD:.0f}원)"
              + (f" · 끊김: {s['error']}" if s["error"] else ""))
        for b in s["ranks"]:
            print(f"      {b['순위']}위 {b['메뉴명']} — {b['맥주']} {b['원_ml']}원/ml")
        for e in s["excluded"]:
            print(f"      제외 {e['안_id']}: {e['사유']}")
        print()


# ══════════════════════════════════════════
# 집계
# ══════════════════════════════════════════

def latest_results() -> Path | None:
    files = sorted((ROOT / "tests").glob("results_*.json"),
                   key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def report(path: Path | None) -> None:
    path = path or latest_results()
    if not path or not path.exists():
        print("결과 파일이 없다.")
        raise SystemExit(1)
    data = json.loads(path.read_text(encoding="utf-8"))
    runs = data["runs"]
    print(f"{path.name} · 프롬프트 {data['prompt_version']} · {len(runs)}회 실행\n")

    print(f"{'케이스':6} {'회차':3} {'실행':3} {'완주':3} {'제외':3} {'저가':6} "
          f"{'재호출':4} {'되감기':4} {'평균초':6} {'호출':4} {'평균원':6}")
    by_case: dict[str, list] = {}
    for r in runs:
        by_case.setdefault(r["case_id"], []).append(r)

    tot_ranks = tot_low = 0
    costs = []
    for cid in sorted(by_case):
        rs = by_case[cid]
        s_list = [r["summary"] for r in rs]
        done = sum(1 for s in s_list if not s["error"])
        n_ranks = sum(len(s["ranks"]) for s in s_list)
        n_low = sum(s["low_price_pairings"] for s in s_list)
        tot_ranks += n_ranks
        tot_low += n_low
        # 토큰을 기록하기 전 결과(기준선 첫 8건)는 비용이 없다
        with_cost = [s for s in s_list if "cost_usd" in s]
        costs += [s["cost_usd"] for s in with_cost]
        calls = (f"{sum(s['calls'] for s in with_cost) / len(with_cost):>4.1f}"
                 if with_cost else "   -")
        krw = (f"{sum(s['cost_usd'] for s in with_cost) / len(with_cost) * KRW_PER_USD:>6.0f}"
               if with_cost else "     -")
        print(f"{cid:6} {rs[0]['round']:>3} {len(rs):>3} {done:>3} "
              f"{sum(len(s['excluded']) for s in s_list):>3} "
              f"{n_low:>2}/{n_ranks:<3} "
              f"{sum(s['n_rewinds'] for s in s_list):>4} "
              f"{sum(s['n_restarts'] for s in s_list):>4} "
              f"{sum(s['latency_ms'] for s in s_list) / len(s_list) / 1000:>6.1f} "
              f"{calls} {krw}")

    print(f"\n저가 페어링(<{HIGH_PRICE_PER_ML}원/ml) {tot_low}/{tot_ranks}"
          + (f" = {tot_low / tot_ranks:.0%}" if tot_ranks else ""))
    if costs:
        print(f"기획안 1건 비용(유료 단가 기준) 평균 ${sum(costs) / len(costs):.3f}"
              f" ≈ {sum(costs) / len(costs) * KRW_PER_USD:.0f}원, "
              f"최대 ${max(costs):.3f} ≈ {max(costs) * KRW_PER_USD:.0f}원"
              f"  ({len(costs)}건, 환율 {KRW_PER_USD}원/$ 가정)")

    issues: dict[str, int] = {}
    for r in runs:
        for x in r["summary"]["issues"]:
            issues[x] = issues.get(x, 0) + 1
    if issues:
        print("\n남은 경고 (빈도순)")
        for x, n in sorted(issues.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>2}  {x}")


# ══════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--snapshot", action="store_true")
    g.add_argument("--run", nargs="*", metavar="CASE")
    g.add_argument("--report", nargs="?", const="", metavar="FILE")
    a = ap.parse_args()

    if a.snapshot:
        make_snapshot()
    elif a.run is not None:
        run_cases(a.run or None)
    else:
        report(Path(a.report) if a.report else None)


if __name__ == "__main__":
    main()
