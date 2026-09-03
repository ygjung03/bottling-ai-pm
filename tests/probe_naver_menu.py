"""
네이버 플레이스 메뉴 수집 가능성 확인 — 일회성 시험

유행 메뉴 검색 기능(기획서 3-5 ⑤)에서 "이 가게가 그 메뉴를 파는가"를
확인할 방법이 필요하다. 공식 API 는 메뉴를 주지 않으므로
비공식 경로가 쓸 만한지 먼저 본다.

[주의] 이 스크립트는 채택 여부를 판단하기 위한 시험이다.
  네이버 이용약관상 자동화 수집은 제재 대상이 될 수 있다.
  결과가 좋더라도 대량 수집에는 쓰지 않는다. 후보 5～10곳으로 제한하고,
  실패 시 지도 링크만 제공하는 대체 경로를 항상 남긴다.

확인하는 것
  1. 상호로 placeId 를 찾을 수 있는가
  2. placeId 로 메뉴를 받을 수 있는가
  3. 연속 호출이 견디는가

실행
  python -m tests.probe_naver_menu "블랙스미스 자양동"
  python -m tests.probe_naver_menu "블랙스미스 자양동" --repeat 5
"""
import json
import random
import re
import sys
import time
from urllib.parse import quote

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 지연은 필수다. 연속 호출하면 차단된다.
DELAY = (1.5, 3.0)


def sleep() -> None:
    time.sleep(random.uniform(*DELAY))


def line(t: str) -> None:
    print()
    print("=" * 62)
    print(t)
    print("=" * 62)


# ══════════════════════════════════════════
# 1. placeId 찾기
# ══════════════════════════════════════════

def find_place_ids(query: str) -> list[dict]:
    """
    상호로 검색해 placeId 후보를 찾는다.

    nearby_stores 에는 상호·주소·좌표만 있고 placeId 가 없다.
    동명 가게가 있으면 어느 쪽인지 가려야 하므로 주소를 함께 본다.
    """
    url = ("https://map.naver.com/p/api/search/allSearch"
           f"?query={quote(query)}&type=all&searchCoord=&boundary=")
    try:
        r = requests.get(url, headers={
            "User-Agent": UA,
            "Referer": "https://map.naver.com/",
        }, timeout=10)
        print(f"  응답 {r.status_code} / {len(r.content):,} bytes")
        if r.status_code != 200:
            print(f"  본문 앞부분: {r.text[:200]}")
            return []
        data = r.json()
    except Exception as e:
        print(f"  실패: {type(e).__name__} — {e}")
        return []

    # 응답 구조를 모르므로 place 목록을 찾아 들어간다
    out = []
    try:
        items = (data.get("result", {}).get("place", {}).get("list") or [])
        for it in items[:5]:
            out.append({
                "id": it.get("id"),
                "name": it.get("name"),
                "address": it.get("address") or it.get("roadAddress"),
                "category": it.get("category"),
            })
    except Exception as e:
        print(f"  구조 파싱 실패: {e}")
        print(f"  최상위 키: {list(data.keys())}")

    return out


# ══════════════════════════════════════════
# 2. 메뉴 받기
# ══════════════════════════════════════════

GQL_URL = "https://pcmap-api.place.naver.com/graphql"

# 쿼리 스키마는 네이버가 언제든 바꿀 수 있다.
# 이 시험의 목적은 "지금 되는가"를 보는 것이다.
GQL_QUERY = """
query getMenus($restaurantId: String) {
  restaurant(id: $restaurantId) {
    menus { name price description images }
  }
}
"""


def fetch_menu_graphql(place_id: str) -> list | None:
    """GraphQL 엔드포인트로 메뉴를 받아본다."""
    try:
        r = requests.post(GQL_URL, json={
            "operationName": "getMenus",
            "variables": {"restaurantId": str(place_id)},
            "query": GQL_QUERY,
        }, headers={
            "User-Agent": UA,
            "Content-Type": "application/json",
            "Referer": f"https://pcmap.place.naver.com/restaurant/{place_id}/menu/list",
        }, timeout=10)
        print(f"  GraphQL 응답 {r.status_code} / {len(r.content):,} bytes")
        if r.status_code != 200:
            print(f"  본문: {r.text[:300]}")
            return None
        data = r.json()
        if "errors" in data:
            print(f"  GraphQL 오류: {json.dumps(data['errors'], ensure_ascii=False)[:300]}")
            return None
        return (data.get("data", {}).get("restaurant") or {}).get("menus")
    except Exception as e:
        print(f"  실패: {type(e).__name__} — {e}")
        return None


def fetch_menu_html(place_id: str) -> list | None:
    """
    메뉴 페이지 HTML 에서 초기 상태(JSON)를 뽑아본다.

    GraphQL 이 막히면 이쪽이 대안이다. 다만 렌더링 전 HTML 에
    데이터가 들어 있어야 가능하다.
    """
    url = f"https://pcmap.place.naver.com/restaurant/{place_id}/menu/list"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        print(f"  HTML 응답 {r.status_code} / {len(r.content):,} bytes")
        if r.status_code != 200:
            return None

        m = re.search(r"window\.__APOLLO_STATE__\s*=\s*(\{.*?\});", r.text, re.S)
        if not m:
            print("  __APOLLO_STATE__ 없음 — 렌더링 후에만 데이터가 생기는 구조")
            # 메뉴로 보이는 문자열이 아예 없는지 확인
            hits = re.findall(r'"name"\s*:\s*"([^"]{2,20})"', r.text)[:10]
            print(f"  본문에서 찾은 name 후보: {hits}")
            return None

        state = json.loads(m.group(1))
        menus = [v for k, v in state.items() if "Menu" in k and isinstance(v, dict)]
        print(f"  APOLLO_STATE 키 {len(state)}개 / Menu 항목 {len(menus)}개")
        return menus[:10] or None
    except Exception as e:
        print(f"  실패: {type(e).__name__} — {e}")
        return None


# ══════════════════════════════════════════

def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    query = args[0] if args else "블랙스미스 자양동"
    repeat = 1
    if "--repeat" in sys.argv:
        i = sys.argv.index("--repeat")
        repeat = int(sys.argv[i + 1]) if i + 1 < len(sys.argv) else 5

    print(f"검색어: {query}")

    # ── 1 ──
    line("1. 상호로 placeId 찾기")
    places = find_place_ids(query)
    if not places:
        print("\n  placeId 를 찾지 못했다.")
        print("  → 이 경로는 쓸 수 없다. 지도 링크 제공 방식으로 간다.")
        return

    for p in places:
        print(f"  {p['id']}  {p['name']}  ({p['category']})")
        print(f"      {p['address']}")

    place_id = places[0]["id"]
    print(f"\n  첫 결과로 진행: {place_id}")
    sleep()

    # ── 2 ──
    line("2. 메뉴 받기")

    print("\n[A] GraphQL")
    menus = fetch_menu_graphql(place_id)
    if menus:
        print(f"  메뉴 {len(menus)}개")
        for m in menus[:8]:
            print(f"    {m.get('name')}  {m.get('price')}")
    sleep()

    if not menus:
        print("\n[B] HTML 초기 상태")
        menus = fetch_menu_html(place_id)
        if menus:
            print(f"  Menu 항목 {len(menus)}개")
            for m in menus[:5]:
                print(f"    {json.dumps(m, ensure_ascii=False)[:120]}")

    if not menus:
        print("\n  두 방법 모두 메뉴를 얻지 못했다.")
        print("  → Selenium/Playwright 로 렌더링해야 한다는 뜻이다.")
        print("    GitHub Actions 에서 돌리기 무겁고 차단 위험도 크므로,")
        print("    지도 링크 제공 방식을 권한다.")
        return

    # ── 3 ──
    if repeat > 1:
        line(f"3. 연속 호출 {repeat}회 — 차단 여부")
        ok = 0
        for i in range(repeat):
            sleep()
            t0 = time.perf_counter()
            r = fetch_menu_graphql(place_id)
            sec = time.perf_counter() - t0
            state = "성공" if r else "실패"
            if r:
                ok += 1
            print(f"  {i+1}/{repeat}  {state}  {sec:.1f}초")
        print(f"\n  {repeat}회 중 {ok}회 성공")
        if ok < repeat:
            print("  → 중간에 막힌다. 대량 수집은 불가능하다.")

    # ── 판단 ──
    line("판단")
    print("  메뉴를 받을 수 있다.")
    print()
    print("  채택하더라도 아래를 지킨다.")
    print("    · 후보 5～10곳으로 제한. 540곳 전부를 긁지 않는다")
    print("    · 결과를 캐시해 같은 가게를 반복 호출하지 않는다")
    print("    · 실패해도 흐름이 멈추지 않게 하고 지도 링크로 대체한다")
    print("    · 호출 간 1.5～3초 지연")
    print()
    print("  [주의] 스키마와 클래스명이 주기적으로 바뀐다.")
    print("        10월 실증 중에 막히면 고칠 시간이 없으므로")
    print("        대체 경로를 반드시 함께 만들어둔다.")


if __name__ == "__main__":
    main()
