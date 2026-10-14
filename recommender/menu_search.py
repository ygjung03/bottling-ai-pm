"""
메뉴로 찾기 — 그 메뉴를 다루는 근처 가게를 점수 순으로 (명세서 3-5 · 4-3 경로 C, W5 A-1-2)

    메뉴 이름 → 관련 업종의 점수 상위 후보 → 가게마다 네이버 블로그 「가게명 + 메뉴」
              → 후기에 가게 이름과 메뉴가 함께 나오는 글 수 = 언급 수
              → 언급이 있는 곳 먼저, 그 안에서는 추천 점수 순

[가게를 새로 찾지 않는다]
  검색으로 가게를 「찾아오지」 않고, 이미 점수가 매겨진 nearby_stores 후보마다
  「이 가게 후기에 그 메뉴가 나오나」만 묻는다. 그래서 결과에 나오는 가게는 모두
  DB 에 있다 (W5 「두 탭에서 공통으로 지킬 것」). 지역검색으로 메뉴를 찾으면 한 번에
  5곳밖에 안 주고, 받은 이름을 DB 와 맞추는 데서 또 빠진다.

[언급 0건을 버리지 않는다]
  작은 가게는 블로그에 이름이 오르지 않는다. 0건이라고 안 파는 게 아니라서 화면은
  지우지 않고 접는다 (명세서 4-3 경로 C).

[네이버 키]
  NCP(API HUB) 키 — collectors/menu_reviews.py 와 같은 주소·헤더. 개발자센터
  주소로 부르면 401.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

import requests

from collectors.menu_reviews import area_of
from config.settings import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET

BLOG_URL = "https://naverapihub.apigw.ntruss.com/search/v1/blog"
MAX_STORES = 30      # 점수 상위 몇 곳까지 검색할지. 가게마다 1회 호출
POSTS_PER_STORE = 30
WORKERS = 8
TOP_N = 5
# 바틀링 반경 1km 안에서 지점명에 붙는 지명 (상가 자료 상호 기준)
BRANCH = (r"(뚝섬유원지|어린이대공원|건대입구|건국대|건대|자양|구의|성수|광진|화양|군자|"
          r"뚝섬|서울숲|능동)?역?(본|직영)?점$")


def _plain(text: str) -> str:
    """태그·공백·기호를 빼고 비교용 글자만 남긴다. 「두바이 초콜릿」=「두바이초콜릿」"""
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"[^가-힣A-Za-z0-9]", "", text).lower()


def name_keys(store_name: str) -> list[str]:
    """
    후기에서 가게를 알아볼 이름들.

    상가 자료의 상호는 붙여 쓰고 지점명이 붙어 있다 — 「삼형제김밥뚝섬유원지점」.
    블로그 제목에는 지점명이 빠지는 일이 많아 「삼형제김밥」도 함께 본다.
    지점명을 떼고 두 글자 이하만 남으면 다른 가게와 겹치므로 쓰지 않는다.
    """
    key = _plain(store_name)
    keys = [key] if key else []
    # 지점명은 아는 지명만 뗀다. 「…[가-힣]+점」으로 떼면 「삼형제김밥뚝섬유원지점」이
    # 「삼형제」까지 잘려 다른 가게 글과 겹친다.
    core = re.sub(BRANCH, "", key)
    if core != key and len(core) >= 3:
        keys.append(core)
    return keys


def count_mentions(store: dict, menu: str) -> dict:
    """
    한 가게의 후기 중 그 가게를 다루면서 메뉴가 나오는 글 수.

    **가게 이름은 제목에서만 본다** (10/14). 글 어디에든 나오기만 하면 세었더니
    여러 가게를 한꺼번에 다루는 글이 전부 걸렸다 — 「붕어빵」으로 찾았는데
    카페 「저스트런잇」이 3건이었고, 그 셋이 「2024.05.월 일상」·「러닝 난이도별
    가기 좋은 맛집 & 카페」 같은 일상 글과 모음 글이었다. 한 가게를 다룬 후기는
    제목에 그 가게 이름을 적는다.

    메뉴는 제목과 본문 어디에 있어도 센다. 제목은 가게 이름으로 채우고 메뉴는
    본문에서 말하는 글이 많다.

    놓치는 것도 있다 — 「뚝섬 붕어빵 맛집 다녀왔어요」처럼 제목에 가게 이름을
    안 쓴 후기는 0건이 된다. 0건이어도 목록에서 지우지 않고 접어 두므로
    (search 설명) 그 가게가 사라지지는 않는다.

    반환: {"store_id", "mentions", "sample_url", "error"}
    실패해도 0건으로 돌려 나머지 가게는 계속 본다 — 한 곳 때문에 전체가 멈추면 안 된다.
    """
    out = {"store_id": store["store_id"], "mentions": 0, "sample_url": None, "error": None}
    keys, want = name_keys(store.get("name") or ""), _plain(menu)
    if not keys or not want:
        return out
    # 검색어에 구를 붙인다. 상호가 일반명사이면 전국의 같은 낱말 글이 걸린다 —
    # 「프레즐 피자」로 7건이 걸렸는데 전부 다른 브랜드의 「앤티앤스 프레즐」
    # 글이었고, 「광진구」를 붙이니 1건으로 줄었다 (10/14). 수집 쪽이 같은 이유로
    # 이미 쓰는 방법이다 (collectors/menu_reviews.area_of).
    query = " ".join(x for x in (area_of(store.get("address")),
                                 store["name"], menu) if x)
    try:
        r = requests.get(BLOG_URL, timeout=15,
                         params={"query": query,
                                 "display": POSTS_PER_STORE, "sort": "sim"},
                         headers={"X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
                                  "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET})
        r.raise_for_status()
        for it in r.json().get("items") or []:
            title = _plain(it.get("title", ""))
            text = _plain(f"{it.get('title', '')} {it.get('description', '')}")
            if want in text and any(k in title for k in keys):
                out["mentions"] += 1
                out["sample_url"] = out["sample_url"] or it.get("link")
    except Exception as e:
        out["error"] = str(e)[:120]
    return out


def search(menu: str, candidates: list[dict]) -> dict:
    """
    candidates: 점수 높은 순으로 정렬된 nearby_stores 행 (업종 필터를 거친 것).

    반환: {"hits": 언급 있는 곳 점수 순, "top": 그중 상위 TOP_N,
           "misses": 언급 0건 점수 순, "searched": 검색한 가게 수, "errors": 실패 수}
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        raise RuntimeError("네이버 검색 키가 없습니다 (NAVER_CLIENT_ID / NAVER_CLIENT_SECRET).")
    pool = candidates[:MAX_STORES]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        found = list(ex.map(lambda s: count_mentions(s, menu), pool))

    by_id = {f["store_id"]: f for f in found}
    rows = [dict(s, mentions=by_id[s["store_id"]]["mentions"],
                 sample_url=by_id[s["store_id"]]["sample_url"]) for s in pool]
    score = lambda r: float(r.get("score") or 0)
    hits = sorted([r for r in rows if r["mentions"] > 0], key=score, reverse=True)
    misses = sorted([r for r in rows if r["mentions"] == 0], key=score, reverse=True)
    return {"hits": hits, "top": hits[:TOP_N], "misses": misses,
            "searched": len(pool), "errors": sum(1 for f in found if f["error"])}