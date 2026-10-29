"""
협력사 메뉴·판매가를 네이버 블로그 후기에서 모은다 (U17)

[담당] B
[부르는 곳] 기획안 생성 화면의 「메뉴 자동 수집」 버튼
[넣는 곳] partners.menu_prices_review

세 단계다 (시안 docs/ref/기획안생성화면_메뉴정보_figma.pdf 3쪽).

  1 블로그 후기 검색   가게 이름으로 글을 찾는다
  2 메뉴·가격 추출     글 본문을 읽어 메뉴와 가격을 뽑는다
  3 중복 정리          여러 글에 겹쳐 나온 것만 남긴다

[겹치는 것만 쓰는 이유]

후기 한 건에만 나온 메뉴는 그 사람이 잘못 적었거나, 지금은 안 파는 것일 수
있다. 그래서 **서로 다른 글 MIN_POSTS 건 이상에 나온 메뉴만** 등록한다.
후기가 적은 가게는 한 개도 안 나올 수 있고, 그것이 정상이다.

가격은 **한 글 안에 메뉴와 가격이 함께** 적혀 있을 때만 가져온다. 값이 글마다
다르면 많이 나온 쪽을 쓴다. 가격을 못 찾아도 메뉴는 등록하고 가격만 비워 둔다
— 지어내지 않는다(작업 원칙 ③). 비어 있는 값은 대표님이 화면에서 채운다.

[네이버 키]

NCP(API HUB) 키다. 개발자센터 키가 아니라서 주소도 헤더 이름도 다르다.
개발자센터 주소로 부르면 401 이 온다 (10/5 확인).
"""
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import requests

from chain.gemini import call
from config.settings import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
from db import api_usage as usage

KST = timezone(timedelta(hours=9))

SEARCH_BASE = "https://naverapihub.apigw.ntruss.com/search/v1"
SEARCH_URL = f"{SEARCH_BASE}/blog"
POST_URL = "https://blog.naver.com/PostView.naver"
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/126.0 Safari/537.36")}

# 블로그 글을 몇 건이나 볼 것인가. 글마다 제미나이를 한 번 부른다.
#
# 10 건으로는 가격이 적힌 글이 한두 개뿐이라 겹치는 메뉴가 거의 안 나왔다.
# 같은 가게로 재 봤다 (10/5).
#
#   10 건   메뉴 1 개
#   20 건   메뉴 7 개.  값 하나가 틀렸다 (피자 가격이 2,500 원으로)
#   30 건   메뉴 9 개.  가격이 적힌 글이 4 건으로 늘어 올바른 값이 이겼다
#
# 글이 많을수록 겹침 규칙이 제 일을 한다. 틀린 값도 글이 모이면 걸러진다.
MAX_POSTS = 30

# 네이버에 글을 몇 건 달라고 할 것인가. 100 건이 한 번에 받을 수 있는 최대다.
#
# 30 건만 달라고 하면 그중 20 건쯤은 네이버 블로그가 아니다. 「서울 맛집 리스트」
# 같은 티스토리 글인데, 본문을 읽는 방법이 네이버 블로그용뿐이라 그냥 버려진다.
# 100 건을 받으면 읽을 수 있는 글이 훨씬 많이 남는다.
#
#   달라고 한 건수    네이버 블로그   제목에 가게 이름이 있는 글
#        30 건            9 건                2 건
#       100 건           75 건               39 건
#
# 받는 건수를 늘리면 관련도 순서까지 달라졌다. 앞 10 건은 같은데 그 뒤부터
# 벌어진다. 왜 그런지는 네이버 쪽 사정이라 확인하지 못했다.
#
# 많이 받아도 비용은 그대로다. 네이버 검색은 어느 쪽이든 1 회만 부르고, 제미나이는
# 그중 고른 글을 MAX_POSTS 건까지만 읽는다.
ASK_POSTS = 100
# 거르는 기준. 근거가 없는 임계값을 두지 않는다는 원칙(②)과 어긋나 보이지만,
# 이것은 「겹쳐야 믿는다」는 규칙 자체이고 그 아래로는 교차 확인이 성립하지 않는다.
#
# 가격은 기준이 아니다. 가격이 안 적혀 있어도 메뉴 목록에는 등록되게끔 한다
# (10/6 바꿈). 가격까지 있어야 등록되게 했더니 쓸 수 있는 가게가 너무 적었다.
#
#   라쿤피자건대   7개 → 23개
#   저스트런잇     0개 →  3개     생성 버튼이 아예 안 눌리던 가게
#
# 가격이 빈 메뉴는 (2)가 고르지 않는다 (p2 지시 1-0-1). 대표님이 화면에서
# 값을 채우면 그때부터 쓰인다.
MIN_POSTS = 2      # 메뉴 이름이 나온 서로 다른 글 수

# 글 하나에서 제미나이에 넘길 글자 수.
#
# 20,000 자로 늘려 봤더니 오히려 메뉴를 덜 뽑았다 (10/5). 블로그 글 뒤쪽은
# 댓글·다른 글 목록·광고라서, 길게 주면 그 속에서 메뉴를 추리느라 정작
# 메뉴판 부분을 성글게 읽는다. 6,000 자가 메뉴·가격이 들어 있는 앞부분에
# 집중하게 한다.
BODY_LIMIT = 6000


def _strip_html(t: str) -> str:
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def area_of(address: str | None) -> str:
    """
    주소에서 검색어에 붙일 지역 이름을 뽑는다. 없으면 빈 문자열.

    구를 쓴다. 주소가 도로명이라 동이 없기 때문이다 — "서울특별시 광진구
    뚝섬로34길 67". 구만 붙여도 충분히 걸러지는 것을 10/5 에 확인했다.
    """
    m = re.search(r"([가-힣]+구)\s", f"{address or ''} ")
    return m.group(1) if m else ""


def official_name(shop: str, area: str) -> str:
    """
    네이버 지역검색이 아는 정식 상호. 못 찾으면 등록된 이름을 그대로 돌려준다.

    상가 자료의 상호는 띄어쓰기가 없거나 지점 이름이 줄어 있어서, 블로그 글에
    쓰이는 이름과 다르다. 정식 상호로 찾으면 그 가게 글이 더 많이 걸린다 (10/6).

      팔자좀피자    → 팔자좀피자 자양점      4/30 → 11/25
      라쿤피자건대   → 라쿤피자 건대본점     22/30 → 26/30

    **글자가 겹칠 때만 쓴다.** 지역검색이 엉뚱한 가게를 집기도 한다 — 「프레즐」
    로 찾으면 같은 구의 「비밀 베이커리 군자점」이 나오는데, 그걸로 블로그를
    찾으면 27/30 이 6/30 으로 떨어진다.
    """
    want = re.sub(r"\s", "", shop)
    try:
        r = requests.get(f"{SEARCH_BASE}/local", timeout=15,
                         params={"query": f"{shop} {area}".strip(), "display": 5,
                                 "format": "json"},
                         headers={"X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
                                  "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET})
        r.raise_for_status()
        for it in r.json().get("items") or []:
            title = _strip_html(it.get("title") or "")
            packed = re.sub(r"\s", "", title)
            if want and (want in packed or packed in want):
                return title
    except Exception:
        pass          # 못 찾아도 수집은 이어 간다 (작업 원칙 ⑤)
    return shop


def name_only(official: str) -> str:
    """
    정식 상호에서 지점 이름을 떼어 낸다.

      누룽지통닭 뚝섬유원지점  →  누룽지통닭
      봉평메밀막국수 자양역점  →  봉평메밀막국수
      라쿤피자 건대 본점      →  라쿤피자 건대
      프레즐                →  프레즐          (떼어 낼 것이 없다)

    검색할 때 쓰는 이름이 아니다. 네이버에는 지점 이름까지 넣어서 찾고, 받아 온
    글 가운데 어느 것을 읽을지 고를 때만 이 이름으로 제목을 확인한다.

    제목에 지점 이름까지 있어야 읽는다고 정하면 읽을 글이 크게 줄어든다. 블로그
    제목에는 「뚝섬유원지 치킨 누룽지통닭 구이 추천」처럼 지점 이름이 빠진 경우가
    많기 때문이다. 읽은 글이 적으면 여러 글에 겹쳐 나오는 메뉴도 적어지고,
    결국 등록되는 메뉴가 줄어든다.

    협력사 일곱 곳으로 두 방식을 비교해 봤다. 지점 이름까지 요구하면 메뉴가
    78개에서 69개로 줄었고, 팔자좀피자는 읽을 글이 1건만 남아 2개에서 0개가
    됐다 (docs/메뉴수집_검색전략_측정기록.md 4-2 ⑤).
    """
    toks = official.split()
    if len(toks) > 1 and re.search(r"점$", toks[-1]):
        return " ".join(toks[:-1])
    return official


def search_terms(shop: str, address: str | None) -> tuple[str, str]:
    """
    검색어와, 글 제목에서 찾을 가게 이름을 함께 돌려준다.

    지역 검색을 한 번 부른다.

    검색어는 정식 상호에 구를 붙인 것이다. 가게 이름만 넣으면 전국의 같은 이름
    가게가 섞여 들어온다. 구를 붙이면 그 동네 글로 좁혀진다. 동까지 넣어 봤지만
    구만 붙인 것과 같거나 못했다 (10/6). 지번 주소를 따로 구해 올 필요가 없다는
    뜻이다.
    """
    area = area_of(address)
    official = official_name(shop, area)
    return f"{official} {area}".strip(), name_only(official)


def search_blogs(query: str, limit: int = ASK_POSTS) -> list[dict]:
    """
    블로그 글을 찾는다. [{제목, 주소, 날짜}]

    query 와 limit 은 search_terms() 와 ASK_POSTS 에서 온다. 네이버 블로그가
    아닌 글은 본문을 읽을 수 없어 여기서 뺀다.

    최신순이 아니라 관련도순이다. 최신순으로 받으면 그 가게와 상관없는 최근
    글이 먼저 와서 뽑을 것이 없다 (10/5 비교). 대신 글이 오래됐을 수 있어
    날짜를 함께 들고 다닌다.
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        raise RuntimeError("네이버 검색 키가 없습니다.")
    r = requests.get(SEARCH_URL, timeout=20,
                     params={"query": query, "display": limit,
                             "sort": "sim", "format": "json"},
                     headers={"X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
                              "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET})
    r.raise_for_status()
    out = []
    for it in r.json().get("items") or []:
        link = it.get("link") or ""
        m = re.search(r"blog\.naver\.com/([^/?]+)/(\d+)", link)
        if not m:
            continue   # 네이버 블로그가 아닌 글은 본문을 못 읽는다
        out.append({"제목": _strip_html(it.get("title") or ""),
                    "blog_id": m.group(1), "log_no": m.group(2),
                    "주소": f"https://blog.naver.com/{m.group(1)}/{m.group(2)}",
                    "날짜": it.get("postdate") or ""})
    return out


def pick_posts(blogs: list[dict], shop_name: str,
               limit: int = MAX_POSTS) -> list[dict]:
    """
    받아 온 글 가운데 **제목에 가게 이름이 있는 글만** 골라 돌려준다.

    제목에 가게 이름을 적은 글은 그 가게를 다룬 후기일 가능성이 높고, 그런
    글에 메뉴와 가격이 함께 적혀 있는 경우가 많다. 제목에 가게 이름이 없는
    글은 가게 이름이 본문 어딘가를 스쳐 가는 글이 많아서, 읽어도 메뉴가 잘
    안 나온다.

    실제로 재 보니 그 차이가 분명했다. 누룽지통닭뚝섬유원지점은 읽을 수 있는
    글이 9건이었고 그중 제목에 가게 이름이 있는 글이 2건이었는데, **메뉴가
    나온 글이 그 2건이었다.** 나머지 7건은 모두 0개였다.

    협력사 일곱 곳으로 기존 방식과 비교한 결과다.

      기존 방식   30건을 받아 네이버 블로그 글을 관련도순으로 그대로 읽는다
                 제미나이 139회 호출   메뉴 37개 수집   가격 7개 수집
      이 방식    100건을 받아 그중 제목에 가게 이름이 있는 글만 읽는다
                 제미나이  98회 호출   메뉴 78개 수집   가격 25개 수집

    제미나이 호출 수는 줄어드는데 뽑히는 메뉴는 두 배가 됐다. 상관없는 글을
    읽는 데 쓰던 호출이 그 가게 후기를 읽는 쪽으로 옮겨 가기 때문이다. 자세한
    것은 docs/메뉴수집_검색전략_측정기록.md 3-2·4-2 에 있다.

    [제목에 가게 이름이 있는 글이 하나도 없으면 빈 목록이다]
    그런 가게는 수집해도 얻을 것이 거의 없다고 보고 건너뛴다. 커피더쏠이
    그랬는데, 기존 방식으로 글 14건을 읽어도 메뉴가 0개였다. 빈 목록을
    돌려주면 제미나이를 한 번도 부르지 않으므로 돈이 들지 않는다.

    다만 지역 검색에서 정식 상호를 찾지 못한 가게도 여기서 0건이 될 수 있다. 그
    경우에는 실제 후기가 있어도 수집을 건너뛰게 된다. 화면에서는 수동 등록으로
    넘어갈 수 있고, 협력사를 등록할 때 주소를 받으면 이런 경우를 줄일 수 있다
    (남은_작업 ㉛).

    [띄어쓰기를 떼고 맞춘다]
    「누룽지 통닭」처럼 가게 이름을 띄어 쓴 제목이 흔하다. 그래서 가게 이름을
    그대로 비교하지 않고, 띄어쓰기를 뺀 뒤 맞춰서 같은 가게의 글을 놓치지 않는다.
    """
    want = re.sub(r"\s", "", shop_name)
    if not want:
        return blogs[:limit]
    hit = [b for b in blogs
           if want in re.sub(r"\s", "", b.get("제목") or "")]
    return hit[:limit]


def fetch_body(blog_id: str, log_no: str) -> str | None:
    """
    글 본문. 실패하면 None 이고, 그 글은 그냥 건너뛴다 (작업 원칙 ⑤).

    글이 iframe 안에 있어 blog.naver.com/{id}/{logNo} 로는 껍데기만 온다.
    PostView.naver 가 본문을 직접 준다 (tests/probe_naver_blog.py 로 확인).
    """
    try:
        r = requests.get(POST_URL, headers=UA, timeout=20,
                         params={"blogId": blog_id, "logNo": log_no})
    except Exception:
        return None
    if not r.ok:
        return None
    if "se-main-container" not in r.text and "postViewArea" not in r.text:
        return None
    return _strip_html(r.text)[:BODY_LIMIT]


TRAIT_KINDS = ("분위기", "손님층", "포장", "위치", "붐비는때")


def read_post(body: str, shop: str, title: str = "",
              address: str | None = None) -> dict:
    """
    글 하나에서 넷을 받는다. 한 번 부르고 네 가지를 함께 받는다.

      메뉴        지금까지 하던 것. 메뉴와 가격
      이_가게     이 글이 정말 그 가게 얘기인가
      술_어울림   맥주와 어울린다고 적힌 말
      가게_특성   그 가게만의 사실 (분위기·손님층·포장·위치·붐비는때)

    **호출을 늘리지 않는다.** 글 하나에 한 번이다. 따로 부르면 글 수만큼
    호출이 두 배가 되는데, 합쳐도 되는지는 10/9 에 재 봤다
    (docs/private/기획안_문체_점검_1009.md 7장).

    [이_가게 를 묻는 이유]
    검색으로 고른 글이라도 다른 가게 얘기가 섞인다. 실제로 해당 문제가 발생한 적이 있다.
    메뉴는 여러 글에 겹쳐 나온 것만 쓰므로 한 글이 섞여도 걸러지지만,
    특성과 어울림은 한 글에서 바로 오기 때문에 그 장치가 없다. 그래서
    false 면 그 글에서 받은 특성과 어울림을 버린다.

    가격은 **그 글에 적혀 있을 때만** 채운다. 없으면 None 이고, 뒤에서 거르는
    기준이 된다. 짐작해서 채우면 두 단계 거르기가 뜻을 잃는다.
    """
    out, _ms = call(
        "너는 블로그 후기에서 가게에 대한 사실을 뽑는 일을 한다.\n"
        f"가게 이름: {shop}\n"
        + (f"가게 주소: {address}\n" if address else "")
        + "\n"
        "규칙\n"
        "1. 이 가게에서 파는 메뉴만 뽑는다. 다른 가게 얘기나 글쓴이가 집에서\n"
        "   만든 것은 넣지 않는다.\n"
        "1-1. **글에 나오는 메뉴를 하나도 빠뜨리지 말고 모두 뽑는다.** 글쓴이가\n"
        "   먹은 것만이 아니라 메뉴판 사진을 옮겨 적은 부분과 가격표까지 전부\n"
        "   넣는다. 중요해 보이는 것만 골라 내면 안 된다.\n"
        "1-2. 다만 **마실 것은 넣지 않는다.** 콜라·사이다·생맥주·커피·주스처럼\n"
        "   마시는 것은 빼고 먹는 메뉴만 뽑는다. 바틀링은 맥주를 직접 팔기 때문에\n"
        "   협업으로 사 올 것은 안주와 음식뿐이다.\n"
        "2. 메뉴 이름은 글에 적힌 그대로 쓴다. 줄이거나 바꾸지 않는다.\n"
        "3. 가격은 글에 적혀 있을 때만 숫자로 넣는다. 적혀 있지 않으면 null 로\n"
        "   둔다. **짐작해서 채우지 마라.**\n"
        "4. 가격은 원 단위 숫자만 쓴다. 15,000원 → 15000\n"
        "5. 설명에는 그 메뉴의 구성을 적는다. 이름만 봐서는 어떤 메뉴인지 알 수\n"
        "   없는 경우에 특히 중요하다. 예를 들어 「커플세트」는 어떤 메뉴가\n"
        "   묶여 있는지 확인이 필요하다.\n"
        "   글에 적혀 있을 때만 한 줄로 간추린다. 없으면 null 로 둔다.\n"
        "   **설명을 모른다고 그 메뉴를 빼지 마라.** 설명만 null 로 두고 메뉴는\n"
        "   그대로 넣는다. 설명이 있는 메뉴만 골라 내면 안 된다.\n"
        "   **글에 없는 내용을 지어내지 마라.** 맛이 어땠는지는 빼고 무엇으로\n"
        "   구성된 메뉴인지만 적는다.\n"
        '     (O) "피자 2판 + 사이드 1개 + 음료 2잔"\n'
        '     (O) "바질 페스토와 마스카포네 치즈를 올린 피자"\n'
        '     (X) "겉은 바삭하고 속은 촉촉해서 인기가 많다"\n'
        "6. 메뉴가 하나도 없으면 빈 배열을 낸다.\n"
        "7. 이 글이 정말 위에 적은 그 가게를 다녀온 글인지 판정한다.\n"
        "   다른 가게 얘기가 주인 글이거나, 가게 이름만 스치듯 나오고\n"
        "   실제로는 다른 곳을 다녀온 글이면 false 다.\n"
        "   주소가 함께 주어졌으면 글에 나온 위치와 맞는지도 본다.\n"
        "8. 맥주나 술과 함께 먹으면 좋다고 적힌 말이 있으면 뽑는다.\n"
        "   **글에 적힌 말만** 쓴다. 어울릴 것 같다고 지어내지 마라.\n"
        '     (O) "매콤해서 맥주랑 먹으니 계속 들어간다"\n'
        '     (X) "튀김이라 맥주와 잘 어울릴 것이다"\n'
        "   없으면 빈 배열을 낸다. 없는 것 역시 정상이다.\n"
        "9. 그 가게만의 특성을 뽑는다. 아래 다섯 갈래 중 하나로 적는다.\n"
        "     분위기    가게가 어떤 느낌인지\n"
        "     손님층    주로 누가 오는지\n"
        "     포장      포장이 되는지, 포장하면 어떤지\n"
        "     위치      찾아가는 길, 주변에 무엇이 있는지\n"
        "     붐비는때  언제 사람이 많고 언제 한산한지\n"
        "   **같은 업종 다른 가게에 넣어도 말이 되는 문장은 빼라.**\n"
        '     (O) "지하철역에서 나와 바로 보여서 퇴근길에 들르기 좋다"\n'
        '     (X) "음식이 맛있고 친절하다"\n'
        "   글에 적힌 것만 쓰고, 다섯 갈래에 안 맞으면 넣지 마라.\n"
        "   **갈래마다 한 줄씩만 낸다.** 한 갈래로 쓸 말이 여럿이면 그중\n"
        "   가장 그 가게다운 것 하나를 골라라.\n"
        "   **사실만 한 문장으로 간추려라.** 후기 말투를 그대로 옮기지 말고,\n"
        "   그 사실이 담긴 부분만 짧게 적는다. 글에 없는 말을 더하지는 마라.\n"
        '     (글) "힙하고 젊은 감성으로 꾸며진 매장! 라쿤 인형부터 미니어쳐까지\n'
        '           아기자기한 소품구경하는 재미가 있어요 거기에 올드팝 흘러나와"\n'
        '     (O)  "라쿤 인형과 미니어쳐로 꾸몄고 올드팝이 흐르는 힙한 분위기다"\n'
        "   없으면 빈 배열을 낸다.\n\n"
        '출력 — {"메뉴": [{"이름": "...", "가격": 숫자 또는 null,\n'
        '                  "설명": "..." 또는 null}],\n'
        '         "이_가게": true 또는 false,\n'
        '         "술_어울림": [{"메뉴": "...", "문장": "..."}],\n'
        '         "가게_특성": [{"갈래": "분위기|손님층|포장|위치|붐비는때",\n'
        '                       "문장": "..."}]}\n\n'
        # 제목에만 메뉴 이름이 있는 글이 있다. 본문만 넘기면 그런 메뉴를
        # 놓친다 (10/6).
        f"[후기 제목]\n{title}\n\n[후기 본문]\n{body}",
        # 글에 적힌 것을 그대로 뽑는 일이라 흔들리면 안 된다. 기본값으로 두면
        # 같은 글에서 5개가 나왔다 1개가 나왔다 한다 (10/5 확인).
        temperature=0,
        # 무료 키로 부른다. 넘기는 것이 블로그에 공개된 메뉴와 가격뿐이라,
        # 보낸 내용이 모델 개선에 쓰여도 곤란할 것이 없다. 유료 키는 협력사가
        # 알려준 매입가가 들어가는 기획안 생성에 쓴다 (`chain/runner.py`).
        #
        # 가게 하나에 최대 30번을 부르는데 무료 키는 분당 15회가 한도라 2분쯤
        # 걸린다. 유료 키로는 51초였다 (10/6 측정).
        #
        # **여기는 유료로 바뀔 수 있는 자리다.** 한도에 여러 번 걸리면 그때만
        # 유료로 넘기는 것을 검토 중이다 (`chain/gemini.py` 의 429 처리).
        # 그렇게 되면 한 가게를 수집하는 동안 무료와 유료가 섞인다. 사용량
        # 기록은 그래도 맞게 갈린다 — 「어느 기능인가」로 키를 짐작하지 않고
        # 호출이 실제로 쓴 키를 기준으로 삼기 때문이다 (`db/api_usage.py`).
        paid=False)
    # 시킨 모양대로 오지 않을 때가 있다. 가격도 설명도 안 적힌 글에서는
    # 「메뉴」 칸을 빼고 목록만 보내거나, 묶음 대신 이름만 보내기도 한다.
    # 전에는 여기서 오류가 나고 그 글이 통째로 버려졌다 — 300건 중 11건이
    # 그랬고, 그중에는 메뉴가 잘 적힌 후기도 있었다 (10/6 확인).
    items = out if isinstance(out, list) else (out or {}).get("메뉴") or []
    rows = []
    for m in items:
        if isinstance(m, str):
            name, price, note = m.strip(), None, ""
        elif isinstance(m, dict):
            name = str(m.get("이름") or "").strip()
            price = m.get("가격")
            note = str(m.get("설명") or "").strip()
        else:
            continue
        if not name:
            continue
        # 숫자로 달라고 했지만 「15,000원」처럼 글자로 올 때가 있다.
        if isinstance(price, str):
            digits = re.sub(r"[^\d]", "", price)
            price = int(digits) if digits else None
        elif not isinstance(price, (int, float)):
            price = None
        rows.append({"메뉴": name,
                     "가격": int(price) if price else None,
                     "설명": note or None})

    # 목록만 온 경우에는 메뉴 말고 받을 것이 없다.
    got = out if isinstance(out, dict) else {}

    # 판정이 안 왔으면 이 가게 글이 아닌 것으로 본다. 모르는 것을 「맞다」로
    # 두면 안된다 — 특성 몇 개를
    # 놓치는 것보다 다른 가게 얘기가 제안서 배경에 들어가는 쪽이 훨씬 나쁘다.
    # 메뉴는 버리지 않는다. 그쪽은 여러 글에 겹쳐 나온 것만 쓰므로 잘못된 것이
    # 섞여도 걸러진다.
    mine = bool(got.get("이_가게"))

    pairs, traits = [], []
    for x in got.get("술_어울림") or []:
        if not isinstance(x, dict):
            continue
        menu = str(x.get("메뉴") or "").strip()
        line = str(x.get("문장") or "").strip()
        # 어느 메뉴 얘기인지 없으면 버린다. 이 값은 (2)가 「이 메뉴에 이
        # 맥주가 어울린다」는 근거로 쓸 것이라, 메뉴를 모르면 쓸 자리가 없다.
        if menu and line:
            pairs.append({"메뉴": menu, "문장": line, "출처": title})
    for x in got.get("가게_특성") or []:
        if not isinstance(x, dict):
            continue
        kind = str(x.get("갈래") or "").strip()
        line = str(x.get("문장") or "").strip()
        # 다섯 갈래에 없는 말로 오면 버린다. 갈래가 흩어지면 몇 건에서
        # 나왔는지를 셀 수 없고, 그 건수가 (4)에게 얼마나 믿을지 알려 주는
        # 값이다.
        if kind in TRAIT_KINDS and line:
            traits.append({"갈래": kind, "문장": line, "출처": title})

    return {"메뉴": rows, "이_가게": mine,
            "술_어울림": pairs if mine else [],
            "가게_특성": traits if mine else []}


# 크기·용량 표시. 「(R)」·「(L)」·「(대)」·「500ml」 같은 것.
# 괄호가 없는 용량도 떼야 「제로콜라」와 「제로콜라 500ml」이 한 메뉴로 묶인다.
SIZE_MARK = re.compile(
    r"\((?:[RLSrls]|대|중|소|라지|레귤러|스몰)\)"
    r"|\d+\s*(?:ml|ML|mL|L|리터|g|G|kg|인분|개입)")


def same_menu(name: str) -> str:
    """
    여러 글에 나온 메뉴가 서로 같은 메뉴인지 맞춰 보려고 이름을 다듬는다.
    **맞춰 보는 데만 쓴다. 메뉴를 등록할 때는 이 이름을 쓰지 않는다.**

    글쓴이마다 적는 법이 달라서 글자 그대로 맞춰 보면 같은 메뉴가 서로 다른
    메뉴로 세어진다. 실제로 그 때문에 하나도 못 건졌다 (10/5).

      바질마스카포네 피자  ·  바질마스카포네피자  ·  바질마스카포네피자(R)
      페이보릿 투움바 파스타  ·  페이보릿투움바파스타

    띄어쓰기와 크기 표시를 떼면 같은 메뉴로 묶인다. 크기를 떼는 것은 **같은
    메뉴인지 알아보려는 것일 뿐**이고, 등록할 때는 가격이 적혀 있던 글의 이름을
    그대로 쓴다. 그래야 「(R) 22,800원」이 「22,800원」으로 둔갑하지 않는다.
    """
    return re.sub(r"[\s·&,\-]", "", SIZE_MARK.sub("", name))


def _tidy(found: list[tuple[dict, list[dict]]]) -> list[dict]:
    """
    3단계 — 중복 정리. 여러 글에 겹쳐 나온 메뉴만 남긴다.

    found 는 (글, 그 글에서 뽑은 메뉴들) 의 목록이다.

    한 글 안에 같은 메뉴가 여러 번 나와도 한 번으로 센다. 글 하나가 두 글처럼
    세어지면 「서로 다른 글 2건 이상」이라는 기준이 무너진다.
    """
    today = datetime.now(KST).date().isoformat()
    # 다듬은 이름 → 그 메뉴가 나온 글 주소들
    posts: dict[str, set[str]] = defaultdict(set)
    # 다듬은 이름 → (가격, 글 주소, 글 날짜, 그 글에 적힌 메뉴 이름)
    priced: dict[str, list[tuple[int, str, str, str]]] = defaultdict(list)
    # 다듬은 이름 → 글마다 어떻게 적었나. 가격이 없을 때 쓸 이름을 고르려고.
    spelling: dict[str, Counter] = defaultdict(Counter)
    # 다듬은 이름 → 설명이 적힌 글이 있으면 그 설명
    notes: dict[str, str] = {}
    for post, rows in found:
        counted: set[tuple] = set()
        for r in rows:
            key = same_menu(r["메뉴"])
            if not key:
                continue
            posts[key].add(post["주소"])
            spelling[key][r["메뉴"]] += 1
            if r.get("설명") and key not in notes:
                notes[key] = r["설명"]
            if r["가격"] and (key, r["가격"]) not in counted:
                counted.add((key, r["가격"]))
                priced[key].append(
                    (r["가격"], post["주소"], post["날짜"], r["메뉴"]))

    out = []
    for key, urls in posts.items():
        if len(urls) < MIN_POSTS:
            continue                   # 글 하나에만 나온 메뉴는 버린다

        hits = priced.get(key) or []
        if hits:
            # 글마다 가격이 다르면 가장 많이 나온 값을, 그래도 같으면 최근 글의 값.
            top = Counter(p for p, _, _, _ in hits).most_common()
            price = max((p for p, n in top if n == top[0][1]),
                        key=lambda p: max(d for q, _, d, _ in hits if q == p))
            # 가격이 적혀 있던 글의 이름을 그대로 쓴다 (same_menu 설명 참고).
            _, url, _, name = next(h for h in hits if h[0] == price)
            basis = f"후기 {len(urls)}건 중 가격 {len(hits)}건"
        else:
            # 가격을 못 찾아도 메뉴는 넣는다. 대표님이 화면에서 값을 채울 수
            # 있고, 그 전까지는 (2)가 이 메뉴를 고르지 않는다 (p2 지시 1-0-1).
            price, url = None, sorted(urls)[0]
            name = spelling[key].most_common(1)[0][0]
            basis = f"후기 {len(urls)}건, 가격은 못 찾음"

        out.append({
            "메뉴": name, "가격": price, "납품가": None, "출처": url,
            "설명": notes.get(key),
            # 맨 앞 말이 「자동 수집」 표시다 (chain/inputs.MENU_AUTO_BASIS).
            "근거": f"블로그 후기 자동 수집, {basis}, {today}",
        })
    return sorted(out, key=lambda r: r["메뉴"])


TRAIT_QUESTION = {
    "분위기": "가게가 어떤 느낌인가",
    "손님층": "주로 누가 오는가",
    "포장": "포장·배달이 되는가, 포장해서 어디로 가져가는가",
    "위치": "어디에 있고 어떻게 가는가",
    "붐비는때": "언제 사람이 많은가",
}


def merge_traits(shop: str, rows: list[dict]) -> list[dict]:
    """
    글마다 따로 뽑은 특성을 한자리에 놓고 같은 의미의 말을 묶는다.
    **갈래마다 한 번씩 부른다.**

    [왜 추가로 llm을 부르나]
    글 하나마다 따로 부르기 때문에, 글 7 을 읽는 호출은 글 1~6 에 무엇이
    있었는지 모른다. 그래서 「여러 글에 겹쳐 나오는가」를 그 자리에서는 알
    수 없다. 다 읽은 뒤 한 번 더 불러야 볼 수 있다.

    실제로 한 피자가게에서 「자양역 1번 출구 도보 5분」·「자양역 4번 출구로 금방」·
    「자양역 인근이라 접근성이 좋다」가 따로 올라와 세 줄을 차지했다 (10/30).
    같은 말이고, 묶으면 한 줄에 「후기 3건」이 된다.

    [고르지 않고 묶기만 한다]
    몇 줄까지 남길지, 몇 건부터 믿을지는 정하지 않는다 — 그 기준을 세울
    근거가 없다 (작업 원칙 ②). 묶어서 건수를 보이고 판단은 (4)가 한다.

    [건수는 코드가 센다]
    글마다 번호를 매겨 주고 어느 번호끼리 묶였는지를 받는다. 몇 건인지를
    세어 달라고 하면 그 숫자가 틀릴 수 있는데, 그 건수가 (4)에게 얼마나
    믿을지 알려 주는 값이라 틀리면 안 된다.

    [왜 갈래마다 따로 부르나]
    다섯 갈래를 한 번에 주고 묶으라고 했더니 거의 안 묶였다 (10/30). 묶으라고
    예시로 적어 준 바로 그 세 문장이 따로 나왔다. 한 번에 백 줄 가까이 보면서
    묶기·대표 문장 고르기·번호 모으기를 함께 시킨 탓으로 보인다. 갈래마다
    나눠 부르면 한 번에 보는 것이 스무 줄 남짓이고 「이 중에 같은 답은?」
    하나만 묻게 된다. 갈래가 섞여 오는 것도 함께 막힌다.
    """
    merged = []
    for kind in TRAIT_KINDS:          # 적는 순서를 고정한다
        # 번호는 갈래 안에서 1부터 매긴다. 전체 번호를 쓰면 1, 7, 23 처럼
        # 띄엄띄엄해져 고르는 쪽이 헷갈린다.
        mine = [r for r in rows if r["갈래"] == kind]
        if not mine:
            continue
        merged += _merge_one(shop, kind, mine)
    return merged


def _merge_one(shop: str, kind: str, rows: list[dict]) -> list[dict]:
    """갈래 하나를 묶는다. 호출 한 번."""
    listed = "\n".join(f"{i}. {r['문장']}" for i, r in enumerate(rows, 1))
    out, _ms = call(
        "너는 한 가게에 대한 블로그 후기에서 뽑아 둔 문장들을 정리한다.\n"
        f"가게 이름: {shop}\n\n"
        f"아래는 후기 여러 건에서 「{kind}」에 대해 한 줄씩 뽑은 것이다.\n"
        f"다시 말해 전부 **{TRAIT_QUESTION[kind]}**에 대한 답이다.\n"
        "글이 달라도 같은 답을 한 경우가 많다. 같은 답끼리 묶어라.\n\n"
        "규칙\n"
        "1. **같은 답이면 하나로 묶는다. 세부가 달라도 묶는다.**\n"
        "   출구 번호나 분 단위가 다른 것은 다른 답이 아니다.\n"
        '     묶는다) "자양역 1번 출구에서 도보 5분"\n'
        '             "자양역 4번 출구로 나오면 금방"\n'
        '             "자양역 인근이라 접근성이 좋다"   → 자양역에서 가깝다\n'
        '     안 묶는다) "자양역에서 도보 5분" 과 "뚝섬한강공원에서 도보 5분"\n'
        "             → 어디서 가까운지가 다르다\n"
        "2. 묶은 줄의 문장은 그중 가장 또렷한 것을 골라 쓴다. **글에 없는\n"
        "   말을 더하지 마라.** 여러 줄을 합쳐 새 문장을 짓지도 마라.\n"
        "3. 묶인 줄의 번호를 모두 적는다. 혼자인 줄도 그 번호 하나를 적는다.\n"
        "4. **어느 가게에나 해당하는 말은 빼라.** 그 가게만의 사실이 아니다.\n"
        '     (O) "뚝섬유원지 갈 때 포장해 가기 좋다"\n'
        '     (X) "항상 손님이 많다" · "분위기가 좋다"\n'
        f"5. 「{kind}」와 상관없는 줄이 섞여 있으면 빼라.\n"
        "6. 남길 개수를 맞추려 하지 마라. 묶고 나서 남는 만큼만 낸다.\n\n"
        '출력 — {"묶음": [{"문장": "...", "번호": [1, 4, 7]}]}\n\n'
        f"[뽑아 둔 문장]\n{listed}",
        temperature=0, paid=False)

    got = (out or {}).get("묶음") if isinstance(out, dict) else out
    merged = []
    for g in got or []:
        if not isinstance(g, dict):
            continue
        line = str(g.get("문장") or "").strip()
        # 번호가 어긋나 오면 그 줄만 버린다 (작업 원칙 ⑤).
        nums = [n for n in (g.get("번호") or [])
                if isinstance(n, int) and 1 <= n <= len(rows)]
        if line and nums:
            merged.append({"갈래": kind, "문장": line,
                           "근거": f"후기 {len(nums)}건",
                           "출처": [rows[n - 1]["출처"] for n in nums][:3]})
    return merged


def _traits(shop: str, reads: list[dict]) -> dict:
    """
    글마다 받은 특성을 한자리에 모아 묶는다 (merge_traits). 그 결과를
    partners.review_traits 에 그대로 넣는다.

    **몇 건에서 나왔는지를 함께 적는다.** 여러 글이 같은 말을 하면 그 가게
    얘기일 가능성이 높다. 몇 건부터 믿을지는 정하지 않는다 — 그 기준을 세울
    근거가 없다 (작업 원칙 ②). 건수를 보이고 판단은 (4)가 한다.

    갈래마다 문장은 세 개까지만 둔다. 다 실으면 (4) 입력이 길어지는데,
    같은 갈래의 네 번째 문장이 더 보태 주는 것이 적다.

    술 어울림은 묶지 않는다. 메뉴마다 다른 말이라 갈래가 없다.
    """
    kinds: dict[str, list[dict]] = {}
    for got in reads:
        for t in got.get("가게_특성") or []:
            kinds.setdefault(t["갈래"], []).append(t)

    # 자르지 않고 전부 넘긴다. 여기서 갈래당 몇 개로 줄이면 같은 말만 남고
    # 다른 말이 버려질 수 있다 — 묶기 전에는 어느 것이 같은 말인지 모른다.
    rows = [t for kind in TRAIT_KINDS for t in kinds.get(kind) or []]
    out = merge_traits(shop, rows) if rows else []

    seen, pairs = set(), []
    for got in reads:
        for p in got.get("술_어울림") or []:
            key = (p["메뉴"], p["문장"])
            if key not in seen:
                seen.add(key)
                pairs.append(p)

    return {"가게_특성": out, "술_어울림": pairs,
            "수집일": datetime.now(KST).date().isoformat()}


def collect(shop: str, address: str | None = None, on_step=None,
            partner_id: int | None = None) -> dict:
    """
    가게 하나의 메뉴·가격을 모은다.

    on_step(단계, 상태) 로 진행을 알린다. 화면이 그걸 보고 세 칸을 칠한다.

    돌려주는 것
      메뉴    두 번 걸러서 남은 메뉴들. 그대로 menu_prices_review 에 넣으면 된다
      찾음    네이버 검색 api 로 받아온 네이버 블로그 글이 몇 개인가
      글      그중 읽기로 고른 글이 몇 개인가 (제목에 가게 이름이 있는 글)
      읽음    그중 본문까지 실제로 받아온 글이 몇 개인가
      검색어  실제로 검색창에 넣은 말 (가게 이름 + 구)

    [찾음, 글, 읽음을 따로 세는 이유]
    단계마다 줄어드는 이유가 다르고, 그에 따라 사람이 할 일도 다르다.

      찾음 0               그 가게 글이 네이버에 거의 없다
      찾음 20, 글 0        글은 있지만 제목에 가게 이름을 적은 글이 없다.
                          이름이 안 맞을 수도 있다 (pick_posts 설명 참고)
      글 8,  읽음 0        읽을 글은 골랐는데 본문을 하나도 못 받아왔다.
                          수집이 막힌 것이라 사람이 봐야 한다

    본문은 검색 api 가 주는 게 아니라 블로그 페이지를 직접 받아와야 한다.
    그래서 실패할 수 있다 — 지워진 글, 페이지 생김새가 바뀐 경우다. 실패한
    글은 그냥 넘어간다 (작업 원칙 ⑤).

    9/3 에 네이버 플레이스 메뉴 수집이 캡차로 막힌 적이 있다. 같은 일이 블로그
    쪽에 생기면 이 두 숫자가 벌어지는 것으로 바로 알아챌 수 있다.

    [partner_id]
    사용량 기록에만 쓴다. 등록된 협력사로 수집하면 앱이 넘겨 주고, 아직 등록
    안 된 가게로 수집하면 빈다 — 「메뉴로 가게 찾기」는 등록 전에도 돌 수 있다.
    비어 있어도 가게 이름은 남으므로 집계는 된다 (db/api_usage.py).
    """
    def step(n, state):
        if on_step:
            on_step(n, state)

    # 이 가게에 쓴 것만 세도록 여기서 0 으로 돌린다
    usage.start()

    step(1, "진행 중")
    query, shop_name = search_terms(shop, address)   # 지역검색이 한 번 들어 있다
    hits = search_blogs(query)
    blogs = pick_posts(hits, shop_name)
    step(1, "완료")

    step(2, "진행 중")
    found, reads = [], []
    for b in blogs:
        body = fetch_body(b["blog_id"], b["log_no"])
        if not body:
            continue          # 못 읽는 글은 건너뛴다 (작업 원칙 ⑤)
        try:
            got = read_post(body, shop, b["제목"], address)
        except Exception:
            continue
        found.append((b, got["메뉴"]))
        reads.append(got)
    step(2, "완료")

    step(3, "진행 중")
    menus = _tidy(found)
    traits = _traits(shop, reads)
    step(3, "완료")
    # 무료 키와 유료 키가 섞여 있으면 키마다 한 줄씩 남는다 (db/api_usage.py).
    usage.record(usage.COLLECT, partner_id=partner_id, partner_name=shop,
                 note=f"후기 {len(hits)}건 중 {len(blogs)}건 골라 "
                      f"{len(found)}건 읽음")
    return {"메뉴": menus, "특성": traits, "찾음": len(hits), "글": len(blogs),
            "읽음": len(found), "검색어": query}


if __name__ == "__main__":
    # 확인용. 협력사 이름을 주면 DB 에서 주소를 찾아 함께 쓴다.
    #   python -m collectors.menu_reviews "라쿤피자건대"
    import sys

    from db.client import get_client

    name = sys.argv[1] if len(sys.argv) > 1 else "라쿤피자건대"
    row = (get_client().table("partners").select("name,address")
           .eq("name", name).limit(1).execute().data or [{}])[0]

    res = collect(name, row.get("address"),
                  on_step=lambda n, s: print(f"  ({n}/3) {s}"))
    print(f"\n검색어: {res['검색어']}")
    print(f"글 {res['글']}건 중 {res['읽음']}건을 읽어 메뉴 {len(res['메뉴'])}개\n")
    for r in res["메뉴"]:
        won = f"{r['가격']:,}원" if r["가격"] else "가격 없음"
        print(f"  {r['메뉴']:<24} {won:>10}   {r['근거']}")
        if r.get("설명"):
            print(f"      구성  {r['설명']}")
    if not res["메뉴"]:
        print("  (조건을 넘은 메뉴가 없다)")
