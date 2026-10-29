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
import re
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
from chain.loader import load as load_prompt, render
from chain.runner import run
from context.builder import build as build_context

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TESTSET = FIXTURES / "testset.json"
SNAPSHOT = FIXTURES / "snapshot.json"
PROMPTS = ROOT / "prompts"

KST = timezone(timedelta(hours=9))
NO_FEWSHOT = "(없음 — 채택 사례가 아직 없다)"

# 유료 등급 단가 (ai.google.dev/gemini-api/docs/pricing, 2026-09-18, gemini-3.5-flash-lite).
# 무료 키로 돌리면 실제론 0원이지만 대표님 키(유료)로 돌리면 얼마인지를 본다.
USD_PER_M_INPUT = 0.30
USD_PER_M_OUTPUT = 2.50
KRW_PER_USD = 1350   # 환산용 가정 (2026-10-06 기준). 정확한 환율이 아니다


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

def case_date(case: dict, ts: dict) -> str:
    """케이스의 대상일. 안 적혀 있으면 테스트셋 전체의 기본값을 쓴다."""
    return case.get("target_date") or ts["target_date"]


def make_snapshot() -> None:
    """
    입력을 날짜별로 박아 둔다.

    대상일이 다르면 상권 컨텍스트도 행사 목록도 달라진다. 날짜마다 그 날짜에
    쓰이는 업종만 만든다 — 모든 날짜 × 모든 업종을 만들면 파일만 커진다.
    """
    ts = load_testset()
    need: dict[str, set] = {}
    for c in ts["cases"]:
        need.setdefault(case_date(c, ts), set()).add(c["partner"]["category"])

    by_date = {}
    for d, cats in sorted(need.items()):
        target = date.fromisoformat(d)
        print(f"대상일 {d} / 업종 {sorted(cats)}")
        contexts = {}
        for cat in sorted(cats):
            print(f"  컨텍스트 — {cat}")
            contexts[cat] = build_context(target, partner_category=cat)
        by_date[d] = {"contexts": contexts, "events": build_events(target)}

    snap = {
        "built_at": datetime.now(KST).isoformat(timespec="seconds"),
        "by_date": by_date,
        "beer_list": build_beer_list(),
        "constraints": build_constraints(),
    }
    SNAPSHOT.write_text(json.dumps(snap, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"저장 → {SNAPSHOT.relative_to(ROOT)}")
    for d, v in by_date.items():
        for cat, ctx in v["contexts"].items():
            print(f"  {d} {cat:12} {len(ctx):>6}자")


def load_snapshot() -> dict:
    if not SNAPSHOT.exists():
        print("snapshot.json 이 없다. 먼저 --snapshot 을 돌릴 것.")
        raise SystemExit(1)
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


# ══════════════════════════════════════════
# 실행
# ══════════════════════════════════════════

PROPOSAL_FIELDS = ("역할분담", "상호_이익", "배경", "매입")


def summarize(r: dict) -> dict:
    """체인 결과에서 비교에 쓸 숫자만 뽑는다. 원문은 output 에 따로 남긴다."""
    menus = (r["p2"] or {}).get("메뉴안") or []
    final = r["final"] or {}
    plans = final.get("안") or []
    excluded = final.get("제외") or []

    items = []
    for a in plans:
        b = a.get("페어링_맥주") or {}
        items.append({
            "안_id": a.get("안_id"), "접근": a.get("접근"), "메뉴명": a.get("메뉴명"),
            "맥주": b.get("메뉴명"), "원_ml": b.get("원_ml"),
            # 대표가 어느 안을 골라도 제안서가 나와야 한다 — 4필드가 다 있어야 함
            "제안서_필드": sum(bool(a.get(k)) for k in PROPOSAL_FIELDS),
        })

    return {
        "error": r["error"],
        "menus": [m.get("메뉴명") for m in menus],
        "approaches": [m.get("접근") for m in menus],
        "items": items,
        "excluded": [{"안_id": e.get("안_id"), "사유": e.get("제외_사유")}
                     for e in excluded],
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
        tdate = case_date(c, ts)
        day = snap["by_date"][tdate]
        print(f"[{c['id']}] {partner['name']} · {c['round']}차 · {tdate}")

        args = dict(
            context=day["contexts"][cat],
            target_date=tdate,
            beer_list=snap["beer_list"],
            partner_res=build_partner_resources(partner),
            partner_blockers=build_partner_blockers(partner),
            bottling_ingredients=BOTTLING_INGREDIENTS,
            margin_ref=MARGIN_REF,
            weather_pref=WEATHER_PREF,
            trend_menu=NO_TREND_MENU,
            # 제약은 스냅샷에서 읽지 않고 그때그때 만든다. 스냅샷이 얼리는
            # 것은 **데이터**(상권·행사·맥주)다 — 그것이 흔들리면 프롬프트를
            # 고친 효과를 가릴 수 있어서다. 제약은 데이터가 아니라 프롬프트의
            # 일부라, 얼려 두면 고쳐도 고정 테스트에 안 먹는다. 실제로
            # constraints.yaml 의 말투 규칙을 고쳤는데 9/26 스냅샷에 박힌
            # 옛 문장이 돌았다 (10/30).
            constraints=build_constraints(),
            fewshot=NO_FEWSHOT,
            bottling_sns=BOTTLING_SNS,
            partner_sns=build_partner_sns(partner),
            events=day["events"],
            past_cases=PAST_CASES,
            rec_reason=NO_REC_REASON,
            partner=partner,
            today=date.fromisoformat(ts["today"]),
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

        print(f"    {sec:.0f}초 · 메뉴 {len(s['menus'])} {s['approaches']}"
              f" · 안 {len(s['items'])} · 제외 {len(s['excluded'])}"
              f" · 재호출 {s['n_rewinds']} · 되감기 {s['n_restarts']}"
              f" · 호출 {s['calls']}회 {s['tokens_in']:,}/{s['tokens_out']:,} 토큰"
              f" ≈ ${s['cost_usd']:.3f} ({s['cost_usd'] * KRW_PER_USD:.0f}원)"
              + (f" · 끊김: {s['error']}" if s["error"] else ""))
        for it in s["items"]:
            print(f"      {it['안_id']} [{it['접근']}] {it['메뉴명']} — {it['맥주']} "
                  f"{it['원_ml']}원/ml · 제안서 {it['제안서_필드']}/4")
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

    print(f"{'케이스':6} {'회차':3} {'실행':3} {'완주':3} {'안':3} {'제외':3} {'포장':3} "
          f"{'제안서':6} {'재호출':4} {'되감기':4} {'평균초':6} {'호출':4} {'평균원':6}")
    by_case: dict[str, list] = {}
    for r in runs:
        by_case.setdefault(r["case_id"], []).append(r)

    costs = []
    tot_items = tot_full = 0
    for cid in sorted(by_case):
        rs = by_case[cid]
        s_list = [r["summary"] for r in rs]
        done = sum(1 for s in s_list if not s["error"])
        items = [it for s in s_list for it in s["items"]]
        n_pack = sum(1 for s in s_list if "포장" in s["approaches"])
        n_full = sum(1 for it in items if it["제안서_필드"] == 4)
        tot_items += len(items)
        tot_full += n_full
        # 토큰을 기록하기 전 결과는 비용이 없다
        with_cost = [s for s in s_list if "cost_usd" in s]
        costs += [s["cost_usd"] for s in with_cost]
        calls = (f"{sum(s['calls'] for s in with_cost) / len(with_cost):>4.1f}"
                 if with_cost else "   -")
        krw = (f"{sum(s['cost_usd'] for s in with_cost) / len(with_cost) * KRW_PER_USD:>6.0f}"
               if with_cost else "     -")
        print(f"{cid:6} {rs[0]['round']:>3} {len(rs):>3} {done:>3} "
              f"{len(items):>3} "
              f"{sum(len(s['excluded']) for s in s_list):>3} "
              f"{n_pack:>3} "
              f"{n_full:>2}/{len(items):<3} "
              f"{sum(s['n_rewinds'] for s in s_list):>4} "
              f"{sum(s['n_restarts'] for s in s_list):>4} "
              f"{sum(s['latency_ms'] for s in s_list) / len(s_list) / 1000:>6.1f} "
              f"{calls} {krw}")

    print(f"\n제안서 4필드가 다 있는 안 {tot_full}/{tot_items}"
          + (f" = {tot_full / tot_items:.0%}" if tot_items else ""))
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
# 채점 (T14)
# ══════════════════════════════════════════
#
# 기준은 prompts/grader.yaml 이 정본이다. 9/21 에는 손으로 했는데 8건 ×
# 5항목 = 40회라 30분이 걸렸고, 그 뒤로 한 번도 안 돌았다.
#
# **버전끼리 견주는 값이다.** 기획안을 만든 모델과 채점하는 모델이 같아서
# 후하게 볼 수 있다는 한계가 존재한다. 따라서 절대 점수로는 쓰지 않고, 프롬프트를 고치기 전후의 품질을
# 비교해 보는 용도로 쓴다. 
#
# 무료 키로 부른다. 넘기는 것이 우리가 만든 기획안과 공공 상권 데이터뿐이라
# 유료 키를 쓸 자리가 아니다. gemini.call 은 사용량을 DB 에 적지 않는다 —
# 그건 chain.runner.run 이 한다.

ITEMS = ("실행_가능성", "자원_정합성", "상권_근거", "페어링_적절성", "홍보_실효성")


def pick_plan(out: dict) -> dict | None:
    """
    채점할 안 하나. 세트를 먼저 고른다.

    케이스마다 안이 셋이라 다 채점하면 27안이 된다. 기준 문서가 「케이스마다
    하나를 고르되 버전 안에서는 같은 접근으로 맞춘다」고 정해 뒀다. 버전끼리
    견주려면 같은 자리를 봐야 한다.
    """
    plans = (out.get("final") or {}).get("안") or []
    return next((a for a in plans if a.get("접근") == "세트"),
                plans[0] if plans else None)


def grade_one(case: dict, plan: dict, snap: dict, tdate: str) -> dict:
    """안 하나를 채점한다. 무료 키 한 번."""
    partner = case["partner"]
    day = snap["by_date"][tdate]
    prompt = render(
        load_prompt("grader")["prompt"],
        회차=f"{case['round']}차",
        상권_분석=day["contexts"][partner["category"]],
        # 행사는 상권 분석이 아니라 따로 온다. 안 넘기면 행사를 쓴 기획안이
        # 「없는 것을 지어냈다」로 깎인다 (10/30).
        근처_행사=day["events"] or "(없음)",
        맥주_목록=snap["beer_list"],
        협력사_정보=build_partner_resources(partner),
        안=json.dumps(plan, ensure_ascii=False, indent=2))
    # 채점은 글을 짓는 일이 아니라 보는 일이다. 같은 안에 점수가 흔들리면
    # 버전 비교가 뜻을 잃으므로 0 으로 고정한다.
    out, _ms = gemini.call(prompt, temperature=0, paid=False)
    got = (out or {}).get("채점") or out or {}
    rows = {}
    for k in ITEMS:
        v = got.get(k)
        v = v if isinstance(v, dict) else {"점수": v}
        n = v.get("점수")
        rows[k] = {"점수": int(n) if isinstance(n, (int, float)) else None,
                   "메모": str(v.get("메모") or "")}
    return rows


# 추천_근거에 적지 않기로 한 것 (p4 지시 8). 관측 건수와 시간이다.
#
# **이건 코드가 본다.** 패턴이라 사람이 판단할 것이 없고, LLM 에 맡겼더니
# 같은 출력에 1점과 5점이 번갈아 나왔다 (10/30). 흔들리면 버전끼리 견준다는
# 이 도구의 쓸모가 사라진다. 저장소가 이미 그렇게 갈라 놨다 — 기계로 잡을
# 것은 checks.py 가, 판단할 것은 프롬프트가 한다.
COUNT_RE = re.compile(r"\d+\s*건")
COUNT_KO_RE = re.compile(r"(한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|열한|열두)\s*번")
TIME_RE = re.compile(r"\d{1,2}\s*[-~–]\s*\d{1,2}\s*시|\d{1,2}:\d{2}|\d{1,2}\s*시(?!간)")


def rule_breaks(plan: dict) -> list[str]:
    """추천_근거의 상권_지표에 적지 말아야 할 것이 섞였나."""
    text = (plan.get("추천_근거") or {}).get("상권_지표") or ""
    out = []
    m = COUNT_RE.search(text) or COUNT_KO_RE.search(text)
    if m:
        out.append(f"관측 건수 「{m.group(0)}」")
    m = TIME_RE.search(text)
    if m:
        out.append(f"시간 「{m.group(0)}」")
    return out


def verdict(rows: dict) -> tuple[float | None, bool]:
    """평균과 통과 여부. 평균 3.5 이상 **그리고** 1점 항목이 없을 것."""
    got = [r["점수"] for r in rows.values() if r["점수"] is not None]
    if len(got) != len(ITEMS):
        return (None, False)
    avg = sum(got) / len(got)
    return (round(avg, 2), avg >= 3.5 and 1 not in got)


def grade(path: Path | None) -> None:
    path = path or latest_results()
    if not path or not path.exists():
        print("결과 파일이 없다. 먼저 --run 을 돌릴 것.")
        raise SystemExit(1)
    data = json.loads(path.read_text(encoding="utf-8"))
    snap, ts = load_snapshot(), load_testset()
    cases = {c["id"]: c for c in ts["cases"]}

    print(f"{path.name} · {len(data['runs'])}건 · 무료 키로 채점한다\n")
    print(f"{'케이스':7}{'접근':5}" + "".join(f"{k[:2]:>5}" for k in ITEMS)
          + f"{'평균':>7}  판정")

    graded = []
    for r in data["runs"]:
        case, plan = cases.get(r["case_id"]), pick_plan(r["output"])
        if not case or not plan:
            print(f"{r['case_id']:7}채점할 안이 없다 — 건너뛴다")
            continue
        rows = grade_one(case, plan, snap, case_date(case, ts))
        # 코드가 잡은 것으로 상권_근거를 1점 깎는다. 채점이 매긴 점수가
        # 낮았으면 1점까지 내려갈 수 있다.
        breaks = rule_breaks(plan)
        n = rows["상권_근거"]["점수"]
        if breaks and n is not None:
            rows["상권_근거"]["점수"] = max(1, n - 1)
            rows["상권_근거"]["메모"] = (
                f"[코드] {' · '.join(breaks)} 가 들어가 1점 깎았다. "
                + rows["상권_근거"]["메모"])
        avg, ok = verdict(rows)
        graded.append({"case_id": r["case_id"], "round": r["round"],
                       "안_id": plan.get("안_id"), "접근": plan.get("접근"),
                       "규칙어김": breaks, "점수": rows,
                       "평균": avg, "통과": ok})
        cells = "".join(f"{str(rows[k]['점수'] or '-'):>5}" for k in ITEMS)
        print(f"{r['case_id']:7}{str(plan.get('접근') or '-'):5}{cells}"
              f"{str(avg or '-'):>7}  {'통과' if ok else '불합격'}")

    out = ROOT / "tests" / f"grades_{data['prompt_version']}.json"
    out.write_text(json.dumps(
        {"대상": path.name, "prompt_version": data["prompt_version"],
         "채점일": datetime.now(KST).isoformat(timespec="seconds"),
         "채점": graded}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장 → {out.relative_to(ROOT)}")

    done = [g for g in graded if g["평균"] is not None]
    if done:
        print(f"전체 평균 {sum(g['평균'] for g in done) / len(done):.2f} · "
              f"통과 {sum(1 for g in done if g['통과'])}/{len(done)}")
        for k in ITEMS:
            got = [g["점수"][k]["점수"] for g in done
                   if g["점수"][k]["점수"] is not None]
            if got:
                print(f"  {k:<14} {sum(got) / len(got):.2f}")

    # 메모가 왜 그 점수인지 적힌 자리다. 점수만 보면 무엇을 고칠지 모른다.
    print("\n깎인 자리 (3점 이하)")
    hit = False
    for g in graded:
        for k in ITEMS:
            n = g["점수"][k]["점수"]
            if n is not None and n <= 3:
                hit = True
                print(f"  {g['case_id']:5}{k:<14}{n}  {g['점수'][k]['메모']}")
    if not hit:
        print("  없다")


# ══════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--snapshot", action="store_true")
    g.add_argument("--run", nargs="*", metavar="CASE")
    g.add_argument("--report", nargs="?", const="", metavar="FILE")
    g.add_argument("--grade", nargs="?", const="", metavar="FILE")
    a = ap.parse_args()

    if a.snapshot:
        make_snapshot()
    elif a.run is not None:
        run_cases(a.run or None)
    elif a.grade is not None:
        grade(Path(a.grade) if a.grade else None)
    else:
        report(Path(a.report) if a.report else None)


if __name__ == "__main__":
    main()
