"""
메뉴판 사진에서 메뉴와 가격을 읽는다 (③-c, B/C 갈래).

[담당] B

[왜 사진인가]
  B/C 갈래는 협력사가 「전체 메뉴 중에서 다시 추천받고 싶다」고 답한 경우다
  (쟁점_2차흐름과_폼_0925.md 1-3). 후기에서 모은 메뉴는 그 가게가 파는 것의
  일부일 뿐이라, 전체를 보려면 메뉴판을 봐야 한다.

  폼에 올라온 사진은 Apps Script 가 `partner-menus` 버킷으로 옮기고 그 경로를
  `partners.menu_photo_url` 에 남긴다 (`scripts/google_form_sync.gs`).

[무료 키로 부른다]
  메뉴판에는 손님에게 내놓는 판매가만 있고 협력사가 알려준 매입가는 없다.
  가르는 기준은 **보낸 내용이 모델 개선에 쓰여도 괜찮은가** 하나이므로
  (`chain/gemini.py` 의 `get_client`), 블로그 후기를 읽는 것과 같은 쪽이다.
  **매입가가 들어가면 그때 유료로 옮긴다.**

[읽은 값을 그대로 쓰지 않는다]
  잘못 읽은 가격이 그대로 제안서로 가면 안 된다 (작업 원칙 ③). 화면에서
  사람이 확인하고 고친 뒤에 저장한다. 그래서 여기서는 **읽어서 돌려주기만**
  하고 DB 에 쓰지 않는다.
"""
import json

from chain.gemini import call
from db.storage import download_all

# 한 번에 읽는 사진 수. 폼은 여러 장을 받을 수 있는데 전부 한 호출에 넣으면
# 입력이 커지고, 못 읽었을 때 어느 사진 때문인지 가릴 수 없다.
MAX_PHOTOS = 6

PROMPT = """이 사진은 가게 메뉴판이다. 적혀 있는 메뉴와 가격을 읽어라.

규칙
1. 사진에 보이는 **먹는 메뉴**를 하나도 빠뜨리지 말고 모두 적는다.
1-1. 다만 **마실 것은 넣지 않는다.** 콜라·사이다·커피·주스·생맥주처럼
   마시는 것은 빼고 적는다. 바틀링은 맥주를 직접 팔기 때문에 협업으로
   사 올 것은 안주와 음식뿐이다.
2. 메뉴 이름은 사진에 적힌 그대로 쓴다. 줄이거나 바꾸지 마라.
3. 가격은 사진에 보일 때만 숫자로 넣는다. 안 보이면 null 로 둔다.
   **짐작해서 채우지 마라.**
4. 메뉴판이 아니면 빈 목록을 돌려준다. 간판이나 가게 사진일 수 있다.

[출력]
{"메뉴": [{"이름": "...", "가격": 0}]}
"""


def rows_of(out) -> list[dict]:
    """
    모델이 낸 것에서 메뉴 줄만 꺼낸다.

    묶음으로 올 때도 있고 목록을 통째로 낼 때도 있다 — 실제로 목록이 왔다
    (10/13 첫 호출). 묶음으로 믿고 `.get` 을 부르면 그 자리에서 터지므로
    둘 다 받는다 (남은_작업 ㉜).
    """
    if isinstance(out, dict):
        got = out.get("메뉴")
    elif isinstance(out, list):
        # [{"메뉴": [...]}] 처럼 한 겹 싸여 온 경우와 줄이 바로 온 경우를 가른다.
        got = []
        for item in out:
            if isinstance(item, dict) and isinstance(item.get("메뉴"), list):
                got += item["메뉴"]
            elif isinstance(item, dict):
                got.append(item)
    else:
        return []
    return [r for r in (got or []) if isinstance(r, dict)]


def price_of(value) -> int | None:
    """가격을 숫자로. 「2,000원」처럼 와도 읽는다. 못 읽으면 None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    digits = "".join(c for c in str(value or "") if c.isdigit())
    return int(digits) if digits else None


def read_photos(partner: dict, on_step=None) -> dict:
    """
    협력사의 메뉴판 사진을 읽어 메뉴 목록을 돌려준다. DB 에 쓰지 않는다.

    반환
      메뉴      [{"메뉴": 이름, "가격": 숫자 또는 None}]  이름 기준으로 모았다
      읽은_사진  실제로 모델에 넘긴 사진 수
      못_받음    버킷에서 못 받은 경로
      못_읽음    모델이 메뉴를 하나도 못 뽑은 사진 수
      호출       제미나이를 부른 횟수

    on_step(지금, 전체): 사진 한 장을 읽기 시작할 때 부른다 (화면 진행 표시용).
    """
    paths = (partner.get("menu_photo_url") or [])[:MAX_PHOTOS]
    photos, failed = download_all(paths)

    merged: dict[str, dict] = {}
    blank = calls = 0
    for i, (data, mime) in enumerate(photos, 1):
        if on_step:
            on_step(i, len(photos))
        try:
            out, _ms = call(PROMPT, images=[(data, mime)])
            calls += 1
        except Exception as e:
            print(f"[메뉴판 읽기 실패] {i}번째 사진: {type(e).__name__}: {e}")
            blank += 1
            continue

        rows = rows_of(out)
        if not rows:
            blank += 1
            continue
        for r in rows:
            name = str(r.get("이름") or "").strip()
            if not name:
                continue
            # 먼저 읽은 값을 남긴다. 다만 가격이 비어 있던 줄은 채워 준다 —
            # 메뉴판 두 장에 같은 메뉴가 있고 한쪽에만 가격이 보이는 일이 있다.
            kept = merged.setdefault(name, {"메뉴": name, "가격": None})
            if kept["가격"] is None:
                kept["가격"] = price_of(r.get("가격"))

    return {
        "메뉴": list(merged.values()),
        "읽은_사진": len(photos),
        "못_받음": failed,
        "못_읽음": blank,
        "호출": calls,
    }


if __name__ == "__main__":
    # 확인용. 협력사 id 를 주면 그 가게 사진을 읽는다.
    #   python -m collectors.menu_photo 1
    import sys

    from db.client import get_client

    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    row = (get_client().table("partners")
           .select("id,name,menu_photo_url").eq("id", pid).single()
           .execute().data)
    print(f"{row['name']} — 사진 {len(row.get('menu_photo_url') or [])}장")
    got = read_photos(row, on_step=lambda i, n: print(f"  {i}/{n} 읽는 중"))
    print(json.dumps(got, ensure_ascii=False, indent=2))
