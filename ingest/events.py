"""
T10 — 행사 적재 (events)

V9 — 서울시 문화행사 정보
    GET http://openapi.seoul.go.kr:8088/{KEY}/json/culturalEventInfo/{시작}/{끝}/
    - 파라미터 필터가 동작하지 않아 전체(약 19,500건)를 받아 코드에서 필터링한다.
    - 좌표: LOT=경도, LAT=위도 (LON 아님. 실제 응답으로 확인됨)
    - 필터 기준: 바틀링 반경 3km + 오늘부터 향후 30일과 겹치는 일정만

V11 — 네이버 뉴스 검색 (NCP API HUB)
    GET https://naverapihub.apigw.ntruss.com/search/v1/news
    - 헤더 X-NCP-APIGW-API-KEY-ID / X-NCP-APIGW-API-KEY (개발자센터 주소·헤더는 401)
    - 장기 전시 위주인 V9·V10 을 보완해 드론쇼·축제 같은 단기 행사를 찾는다
    - 지역명만으로는 엉뚱한 기사가 섞여, 제목+요약에 LOCATION_KEYWORDS 가 있고
      행사 날짜가 글에서 뽑히는 기사만 남긴다. pubDate 는 기사 날짜라 연도 기준으로만 쓴다

V10 — 광진구청 새소식 게시판(B0000001) 크롤링
    - "문화행사" 검색 시 4건("다음주(N~M) 문화행사 안내" 주간 안내글)만 나옴
    - 게시글 1개 안에 여러 표(행사 여러 건)가 들어있음. 표마다:
        라벨(한 글자씩 셀 분리, 예: "일"|"시") + 값(다음 셀)이 반복되는 구조
    - 좌표 없음 → 장소 텍스트에 뚝섬/자양/한강공원 포함 여부로 관련성 판단
    - robots.txt: 새소식(B0000001)만 허용, Crawl-delay 10초 필수
"""

import math
import os
import re
import time
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from config.settings import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
from db.client import upsert

load_dotenv()

BOTTLING_LAT = float(os.getenv("BOTTLING_LAT", "37.5318919"))
BOTTLING_LNG = float(os.getenv("BOTTLING_LNG", "127.0679483"))

RADIUS_M = 3000
LOOKAHEAD_DAYS = 30
PAGE_SIZE = 1000

GWANGJIN_BASE = "https://www.gwangjin.go.kr"
GWANGJIN_LIST_URL = f"{GWANGJIN_BASE}/portal/bbs/B0000001/list.do"
GWANGJIN_VIEW_URL = f"{GWANGJIN_BASE}/portal/bbs/B0000001/view.do"
GWANGJIN_HEADERS = {"User-Agent": "Mozilla/5.0"}
CRAWL_DELAY_S = 10
LOCATION_KEYWORDS = ["뚝섬", "자양", "한강공원"]


def haversine_m(lat1, lng1, lat2, lng2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_date(value):
    """'2026-12-24 00:00:00.0' -> date(2026, 12, 24). 실패하면 None."""
    if not value:
        return None
    try:
        return datetime.strptime(value.split(" ")[0], "%Y-%m-%d").date()
    except (ValueError, IndexError):
        return None


def fetch_all_seoul_events():
    key = os.getenv("SEOUL_API_KEY")
    if not key:
        raise RuntimeError("SEOUL_API_KEY 가 .env 에 설정되지 않았습니다.")

    all_rows = []
    start = 1
    total = None

    while total is None or start <= total:
        end = start + PAGE_SIZE - 1
        url = f"http://openapi.seoul.go.kr:8088/{key}/json/culturalEventInfo/{start}/{end}/"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()

        block = data.get("culturalEventInfo", {})
        result_code = block.get("RESULT", {}).get("CODE")
        if result_code and result_code != "INFO-000":
            print(f"[경고] {result_code}: {block.get('RESULT', {}).get('MESSAGE')}")
            break

        rows = block.get("row", [])
        all_rows.extend(rows)
        total = block.get("list_total_count", len(rows))

        print(f"  {start}~{end} 수신 ({len(rows)}건, 누적 {len(all_rows)}/{total})")

        if not rows:
            break
        start += PAGE_SIZE

    return all_rows


def filter_and_map(raw_rows):
    today = date.today()
    horizon = today + timedelta(days=LOOKAHEAD_DAYS)

    rows = []
    for it in raw_rows:
        lot, lat = it.get("LOT"), it.get("LAT")
        try:
            lng_f, lat_f = float(lot), float(lat)
        except (TypeError, ValueError):
            continue  # 좌표 없는 행사는 반경 필터를 적용할 수 없어 제외

        distance_m = round(haversine_m(BOTTLING_LAT, BOTTLING_LNG, lat_f, lng_f))
        if distance_m > RADIUS_M:
            continue

        start_date = parse_date(it.get("STRTDATE"))
        end_date = parse_date(it.get("END_DATE"))
        if not start_date or not end_date:
            continue
        if end_date < today or start_date > horizon:
            continue  # 기간이 겹치지 않음

        rows.append({
            "source": "seoul_api",
            "title": it.get("TITLE"),
            "place": it.get("PLACE"),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "lat": lat_f,
            "lng": lng_f,
            "distance_m": distance_m,
            "is_free": (it.get("IS_FREE") == "무료"),
            "url": it.get("HMPG_ADDR") or it.get("ORG_LINK"),
        })

    return rows


def fetch_gwangjin_post_links():
    """새소식 게시판에서 '문화행사' 검색 결과 목록(nttId, 제목)만 뽑는다."""
    params = {"menuNo": 200190, "pageIndex": 1, "searchCnd": 1, "searchWrd": "문화행사"}
    r = requests.get(GWANGJIN_LIST_URL, params=params, headers=GWANGJIN_HEADERS, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    posts = []
    seen = set()
    for a in soup.find_all("a"):
        href = a.get("href") or ""
        if "/bbs/B0000001/view.do" not in href:
            continue
        m = re.search(r"nttId=(\d+)", href)
        if not m:
            continue
        ntt_id = m.group(1)
        if ntt_id in seen:
            continue
        seen.add(ntt_id)
        posts.append({"ntt_id": ntt_id, "title": a.get_text(strip=True)})

    return posts


_DATE_RE = re.compile(r"(\d{4})\.\s?(\d{1,2})\.\s?(\d{1,2})\.?")


def _extract_dates(text):
    """'2026.09.11.(금) ~ 2026.09.12.(토) 오후7시' 같은 텍스트에서 시작/끝 날짜 추출."""
    matches = _DATE_RE.findall(text)
    if not matches:
        return None, None
    dates = [date(int(y), int(m), int(d)) for y, m, d in matches]
    return min(dates), max(dates)


def _extract_table_fields(table):
    """행마다 <th>라벨</th><td>값</td> 구조 — 그대로 짝지어 딕셔너리로 만든다."""
    fields = {}
    for tr in table.find_all("tr"):
        th = tr.find("th")
        td = tr.find("td")
        if th and td:
            fields[th.get_text(strip=True)] = td.get_text(strip=True)
    return fields


DATE_LABELS = ["일시", "공연일시", "공연기간", "교육기간", "교육일정", "모집기간", "신청기간"]
PLACE_LABELS = ["장소", "공연장소", "교육장소"]
FEE_LABELS = ["관람료", "수강료", "참가비"]


def parse_gwangjin_post(ntt_id, post_title):
    params = {"nttId": ntt_id, "menuNo": 200190, "pSiteId": "portal"}
    r = requests.get(GWANGJIN_VIEW_URL, params=params, headers=GWANGJIN_HEADERS, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    detail_url = f"{GWANGJIN_VIEW_URL}?nttId={ntt_id}&menuNo=200190&pSiteId=portal"
    rows = []

    for idx, table in enumerate(soup.find_all("table")):
        fields = _extract_table_fields(table)

        date_text = next((fields[k] for k in DATE_LABELS if k in fields), None)
        place = next((fields[k] for k in PLACE_LABELS if k in fields), None)
        fee_text = next((fields[k] for k in FEE_LABELS if k in fields), "")

        if not place or not any(kw in place for kw in LOCATION_KEYWORDS):
            continue  # 좌표가 없어 장소 텍스트로만 관련성 판단 — 무관한 행사 제외

        start_date, end_date = _extract_dates(date_text or "")
        if not start_date:
            continue
        end_date = end_date or start_date

        today = date.today()
        horizon = today + timedelta(days=LOOKAHEAD_DAYS)
        if end_date < today or start_date > horizon:
            continue  # 향후 30일과 겹치지 않음 (과거 행사 등)

        rows.append({
            "source": "gwangjin_board",
            "title": f"{post_title} #{idx + 1}",
            "place": place,
            "start_date": start_date.isoformat(),
            "end_date": (end_date or start_date).isoformat(),
            "lat": None,
            "lng": None,
            "distance_m": None,
            "is_free": ("무료" in fee_text) if fee_text else None,
            "url": detail_url,
        })

    return rows


def fetch_gwangjin_events():
    posts = fetch_gwangjin_post_links()
    print(f"광진구청 '문화행사' 검색 결과: {len(posts)}건")

    all_rows = []
    for i, post in enumerate(posts):
        rows = parse_gwangjin_post(post["ntt_id"], post["title"])
        print(f"  [{post['title']}] 표 {len(rows)}건 관련 행사 추출")
        all_rows.extend(rows)

        if i < len(posts) - 1:
            time.sleep(CRAWL_DELAY_S)  # robots.txt Crawl-delay 10초 준수

    return all_rows


NEWS_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"
NEWS_QUERIES = ["뚝섬 드론쇼", "뚝섬한강공원 축제", "뚝섬한강공원 행사",
                "자양동 축제", "광진구 축제", "한강공원 페스티벌 뚝섬"]

# 「2026년 10월 18일」「10월 18일」「2026.10.24」 + 「~25일」「부터 3일까지」 같은 끝 날짜
# (?![\d억만천%]) 는 「3.5억」 같은 숫자를 날짜로 잡지 않기 위함
_KDATE_RE = re.compile(
    r"(?:(\d{4})\s*[년.]\s*)?(\d{1,2})\s*[월.]\s*(\d{1,2})(?![\d억만천%])\s*일?"
    r"(?:\s*\([^)]*\))?"
    r"(?:\s*(?:~|-|부터)\s*(?:(\d{1,2})\s*[월.]\s*)?(\d{1,2})\s*일?)?")


def _strip_html(t: str) -> str:
    """검색 결과 제목·요약의 <b> 태그를 뗀다 (collectors/menu_reviews.py 것을 옮김).
    그 모듈을 import 하면 제미나이 설정까지 따라 읽혀서 옮겼다. 태그 자리를 빈칸으로
    두면 「<b>뚝섬</b>한강공원」이 「뚝섬 한강공원」이 돼서 그냥 지운다."""
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", t).strip()


def extract_event_dates(text, pub):
    """기사 글에서 행사 시작·끝 날짜. 연도가 없으면 기사 날짜(pub)의 연도를 쓴다."""
    found = []
    for y, m, d, m2, d2 in _KDATE_RE.findall(text):
        yr = int(y) if y else pub.year
        try:
            s = date(yr, int(m), int(d))
            if not y and pub.month >= 11 and s.month <= 2:   # 12월 기사의 「1월 5일」
                s = s.replace(year=yr + 1)
            e = s
            if d2:
                e = date(s.year, int(m2 or m), int(d2))
                if e < s:
                    e = e.replace(year=e.year + 1)
        except ValueError:
            continue
        if -7 <= (s - pub).days <= 180:      # 기사보다 한참 전 날짜(지난 행사)는 버린다
            found.append((s, e))
    if not found:
        return None, None
    return min(f[0] for f in found), max(f[1] for f in found)


def fetch_naver_news_events():
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        print("[건너뜀] 네이버 키 없음 (NAVER_CLIENT_ID / NAVER_CLIENT_SECRET)")
        return []
    headers = {"X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
               "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET}
    today = date.today()
    horizon = today + timedelta(days=LOOKAHEAD_DAYS)

    rows, seen, seen_ranges = [], set(), set()
    for q in NEWS_QUERIES:
        r = requests.get(NEWS_URL, headers=headers, timeout=15,
                         params={"query": q, "display": 100, "sort": "sim"})
        r.raise_for_status()
        items = r.json().get("items", [])
        kept = 0
        for it in items:
            link = it.get("originallink") or it.get("link")
            if link in seen:                     # 검색어끼리 같은 기사 중복
                continue
            seen.add(link)

            title = _strip_html(it.get("title", ""))
            desc = _strip_html(it.get("description", ""))
            text = f"{title} {desc}"
            if not any(kw in text for kw in LOCATION_KEYWORDS):
                continue                         # 지역과 무관한 기사

            pub = datetime.strptime(it["pubDate"], "%a, %d %b %Y %H:%M:%S %z").date()
            start, end = extract_event_dates(text, pub)
            if not start:
                continue                         # 행사 날짜를 못 뽑은 기사
            if end < today or start > horizon:
                continue  
            if (start, end) in seen_ranges:
                continue                         # 같은 기간 = 같은 행사를 다룬 다른 기사
            seen_ranges.add((start, end))               

            rows.append({
                "source": "naver_news",
                "title": title,
                "place": None,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "lat": None,
                "lng": None,
                "distance_m": None,
                "is_free": None,
                "url": link,
            })
            kept += 1
            print(f"    + {start}~{end}  {title}")
        print(f"  [{q}] {len(items)}건 중 {kept}건 채택")
    return rows


def load():
    print("서울시 문화행사 전체 수집 중 (페이지당 1000건)...")
    seoul_raw = fetch_all_seoul_events()
    print(f"전체 수신: {len(seoul_raw)}건")

    seoul_rows = filter_and_map(seoul_raw)
    print(f"반경 {RADIUS_M}m + 향후 {LOOKAHEAD_DAYS}일 필터 후: {len(seoul_rows)}건")

    time.sleep(CRAWL_DELAY_S)  # 광진구청 요청 전 대기

    print("광진구청 새소식 게시판 수집 중...")
    gwangjin_rows = fetch_gwangjin_events()
    print(f"광진구청 관련 행사: {len(gwangjin_rows)}건")

    print("네이버 뉴스 검색 중...")
    news_rows = fetch_naver_news_events()
    print(f"네이버 뉴스 관련 행사: {len(news_rows)}건")

    all_rows = seoul_rows + gwangjin_rows + news_rows
    if all_rows:
        upsert("events", all_rows, on_conflict="source,title,start_date")
    print(f"총 {len(all_rows)}건 적재 완료 "
          f"(V9 {len(seoul_rows)} + V10 {len(gwangjin_rows)} + V11 {len(news_rows)})")


if __name__ == "__main__":
    load()