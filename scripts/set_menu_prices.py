"""
협력사 메뉴·판매가를 파일에서 읽어 partners.menu_prices 에 넣는다

[담당] B

[임시 경로다] 1차 기획안의 메뉴·판매가는 블로그 후기에서 자동으로 모으기로
  했다(네이버 검색 API). 키가 오기 전까지는 사람이 후기를 보고 적은 것을
  이 스크립트로 넣는다. 수집이 붙으면 그쪽이 같은 컬럼을 채우므로 이 파일은
  지우거나, 수집 결과를 고칠 때만 쓴다.

파일 형식 — JSON 배열. 협력사 정보라 docs/private/ 에 둔다(커밋 안 됨).
  [{"메뉴": "찰식빵", "가격": 5300, "납품가": null, "근거": "블로그 후기, 2026-09-19 확인"}, ...]
  근거는 (2) 셰프가 판매가 뒤에 그대로 읽는다 — 얼마나 믿을 값인지 가늠하라고.

실행
  python -m scripts.set_menu_prices "상호" docs/private/파일.json          보여만 준다
  python -m scripts.set_menu_prices "상호" docs/private/파일.json --apply  반영
"""
import json
import sys
from pathlib import Path

from db.client import get_client


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        return
    name, path = args[0].strip(), Path(args[1])
    rows = json.loads(path.read_text(encoding="utf-8"))

    bad = [r for r in rows if not r.get("메뉴") or not isinstance(r.get("가격"), int)]
    if bad:
        print(f"메뉴 이름이나 가격(정수)이 빠진 줄 {len(bad)}건 — 고치고 다시:")
        for r in bad:
            print(f"  {r}")
        return

    cli = get_client()
    cur = (cli.table("partners").select("id,name,menu_prices")
           .eq("name", name).limit(1).execute().data or [])
    if not cur:
        print(f"'{name}' 협력사가 없다. 먼저 python -m scripts.new_partner 로 만들 것.")
        return
    p = cur[0]

    print(f"{p['name']} (id={p['id']}) — 지금 {len(p.get('menu_prices') or [])}개 → {len(rows)}개")
    for r in rows:
        print(f"  {r['메뉴']:24} {r['가격']:>6,}원  {r.get('근거') or ''}")

    if "--apply" not in sys.argv:
        print("\n--apply 를 붙이면 반영한다. 기존 menu_prices 는 통째로 바뀐다.")
        return
    cli.table("partners").update({"menu_prices": rows}).eq("id", p["id"]).execute()
    print("\n반영 완료.")


if __name__ == "__main__":
    main()
