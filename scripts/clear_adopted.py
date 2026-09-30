"""
보관함 비우기 — 담아 둔 안을 무른다.

시연을 하면 「제안서에 담기」로 고른 것이 쌓인다. 다음 시연을 깨끗한 상태에서
시작하려면 되돌려야 한다.

보관함은 `plans.adopted_option` 이 있는 행만 보여주므로, 그 값만 비우면 화면이
깨끗해진다. plans 행 자체는 남는다 — 그 행이 지난 기획안의 기록이고, 지우면
어떤 결과가 나왔었는지 되짚을 수 없다.

  python -m scripts.clear_adopted            무엇이 담겨 있는지 보기만 한다
  python -m scripts.clear_adopted 프레즐      그 협력사 것을 무른다
  python -m scripts.clear_adopted --all      전부 무른다

[지우지 않고 무른다]
  RLS 로 삭제를 막아 두었다 (db/rls_0928.sql). 협력사 데이터가 사라지는 사고를
  막는 것이 그 목적이고, 여기도 UPDATE 만 쓴다.

  plans 행까지 정말 지워야 하면 Supabase SQL 편집기에서 한다. 거기서는 RLS 가
  적용되지 않는다. 지우기 전에 그 기록이 필요 없는지 확인할 것.

[「최종 선택」은 여기 없다]
  보관함에서 고른 「협력사에 보낸 안」은 브라우저 세션에만 있다. 새로고침하면
  사라지므로 따로 무를 것이 없다. 2차를 실제로 만들면 그때 plans.prev_plan_id
  에 남는다.
"""
import sys

from db.client import get_client


def find(name: str | None) -> list[dict]:
    """담긴 것이 있는 plans. name 을 주면 그 협력사 것만."""
    cli = get_client()
    partners = {p["id"]: p["name"]
                for p in cli.table("partners").select("id,name").execute().data}

    q = (cli.table("plans")
         .select("id,partner_id,round,adopted_option,created_at")
         .not_.is_("adopted_option", "null").order("id", desc=True))
    if name:
        ids = [i for i, n in partners.items() if name in n]
        if not ids:
            raise SystemExit(f"'{name}' 로 찾은 협력사가 없다. "
                             f"있는 것: {', '.join(sorted(partners.values()))}")
        q = q.in_("partner_id", ids)

    rows = q.execute().data or []
    for r in rows:
        r["name"] = partners.get(r["partner_id"], "?")
    return rows


def show(rows: list[dict]) -> None:
    for r in rows:
        print(f"  plan {r['id']:>4}  {r['name']:<14} {r['round']}차  "
              f"{r['adopted_option']}  {r['created_at'][:16]}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    every = "--all" in sys.argv
    name = args[0] if args else None

    if not name and not every:
        rows = find(None)
        print(f"담긴 것이 있는 기획안 {len(rows)}건")
        show(rows)
        print()
        print("무르려면 협력사 이름을 주거나 --all 을 붙인다.")
        print("  python -m scripts.clear_adopted 프레즐")
        return

    rows = find(None if every else name)
    if not rows:
        print("무를 것이 없다.")
        return

    print("무를 것:")
    show(rows)
    if input("\n진행할까요? (y) ").strip().lower() != "y":
        print("취소했다.")
        return

    cli = get_client()
    for r in rows:
        (cli.table("plans")
         .update({"adopted_option": None, "status": "generated"})
         .eq("id", r["id"]).execute())
    print(f"\n{len(rows)}건을 물렀다. 보관함이 비었다.")


if __name__ == "__main__":
    main()
