"""
시연 초기화 — 폼이 채운 값과 담아 둔 안을 되돌린다.

시연을 하면 두 가지가 쌓인다. 구글 폼으로 들어온 협의 결과와, 보관함에 담아
둔 안이다. 다음 시연을 1차부터 깨끗하게 시작하려면 둘 다 되돌려야 한다.

  python -m scripts.reset_demo                무엇이 쌓였는지 보기만 한다
  python -m scripts.reset_demo 테스트용        그 협력사를 되돌린다
  python -m scripts.reset_demo --seed          시연용 협력사 전부

[구글 폼 응답 시트는 따로다]
  응답 시트에서 「모든 응답 삭제」를 눌러도 DB 는 그대로다. 제출되는 순간
  `.gs` 가 이미 Supabase 에 밀어 넣기 때문이다. 그래서 이 스크립트가 필요하다.
  반대로 여기서 비워도 시트의 응답은 남는다 — 시트는 기록이니 둬도 된다.

[지우지 않고 되돌린다]
  RLS 로 삭제를 막아 두었다 (db/rls_0928.sql). 여기도 UPDATE 만 쓴다.

[남기는 것]
  시드 기본값은 건드리지 않는다. 특히 `menu_prices` 는 1차 생성이 쓰는 값이라
  지우면 「메뉴·판매가가 아직 없습니다」로 막힌다. `menu_prices_review`(블로그
  후기)도 폼이 채운 것이 아니므로 그대로 둔다.

[사진 파일]
  `menu_photo_url` 은 비우지만 Supabase Storage 의 사진은 남는다. 용량이
  급하지 않아 그대로 둔다 (남은_작업 ②-3).
"""
import sys

from db.client import get_client
from scripts.clear_adopted import find as find_adopted

# 구글 폼이 채우는 칸과, 비울 때 넣을 값.
#
# 대부분은 NULL 이면 되는데 `blockers`·`menu_photo_url` 은 배열이고
# `NOT NULL DEFAULT '{}'` 다 (db/schema.sql:41,70). NULL 을 넣으면 거부된다.
# 빈 배열도 「없음」으로 읽히므로 화면 동작은 같다.
FORM_COLS = {
    "reply_choice": None, "agreed_menu": None,
    "agreed_sale_price": None, "agreed_price": None,
    "supply_qty": None, "storage_note": None,
    "takeout": None, "takeout_note": None,
    "menu_photo_url": [], "menu_note": None,
    "available_slots": None, "blockers": [], "contact_slots": None,
    "sns_channel": None, "sns_content_type": None,
}

# 2차를 열지 정하는 칸. 이 셋이 비면 화면이 1차로 돌아간다
# (app/pages/2_기획안_생성.py 의 has_form).
GATE_COLS = ("available_slots", "blockers", "sns_channel")


def partners(name: str | None, seed_only: bool) -> list[dict]:
    q = get_client().table("partners").select("*").order("id")
    if seed_only:
        q = q.eq("is_seed", True)
    rows = q.execute().data or []
    if name:
        rows = [r for r in rows if name in r["name"]]
    return rows


def filled(row: dict) -> list[str]:
    """이 협력사에 폼 값이 들어 있는 칸."""
    return [c for c in FORM_COLS if row.get(c)]


def show(rows: list[dict]) -> None:
    for r in rows:
        cols = filled(r)
        gate = "2차 열림" if any(r.get(c) for c in GATE_COLS) else "1차"
        print(f"  [{r['id']}] {r['name']:<14} {gate:<8} 폼 값 {len(cols)}칸"
              + (f"  ({', '.join(cols[:4])}...)" if cols else ""))


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    seed_only = "--seed" in sys.argv
    name = args[0] if args else None

    if not name and not seed_only:
        rows = partners(None, False)
        print(f"협력사 {len(rows)}곳")
        show(rows)
        print()
        print("담긴 안:")
        show_adopted(find_adopted(None))
        print()
        print("되돌리려면 이름을 주거나 --seed 를 붙인다.")
        print("  python -m scripts.reset_demo 테스트용")
        return

    rows = partners(name, seed_only)
    if not rows:
        raise SystemExit("찾은 협력사가 없다.")

    picks = [r for r in rows if filled(r)]
    plans = [p for p in find_adopted(None)
             if p["partner_id"] in {r["id"] for r in rows}]

    print("되돌릴 것:")
    show(rows)
    if plans:
        print("\n담긴 안:")
        show_adopted(plans)
    if not picks and not plans:
        print("\n이미 깨끗하다.")
        return

    if input("\n진행할까요? (y) ").strip().lower() != "y":
        print("취소했다.")
        return

    cli = get_client()
    for r in picks:
        (cli.table("partners").update({c: FORM_COLS[c] for c in filled(r)})
         .eq("id", r["id"]).execute())
    for p in plans:
        (cli.table("plans")
         .update({"adopted_option": None, "status": "generated",
                  "sent_option": None, "sent_at": None})
         .eq("id", p["id"]).execute())

    print(f"\n협력사 {len(picks)}곳, 담긴 안 {len(plans)}건을 되돌렸다.")
    print("화면을 새로고침하면 1차부터 시작된다.")


def show_adopted(rows: list[dict]) -> None:
    for r in rows:
        print(f"  plan {r['id']:>4}  {r['name']:<14} {r['round']}차  "
              f"{r['adopted_option']}")


if __name__ == "__main__":
    main()
