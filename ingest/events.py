"""
T10 — 행사 적재 (events)

V9 — 서울시 문화행사 정보
    GET http://openapi.seoul.go.kr:8088/{KEY}/json/culturalEventInfo/{시작}/{끝}/
    - 파라미터 필터가 동작하지 않아 전체(약 19,500건)를 받아 코드에서 필터링한다.
    - 좌표: LOT=경도, LAT=위도 (LON 아님. 실제 응답으로 확인됨)
    - 필터 기준: 바틀링 반경 3km + 오늘부터 향후 30일과 겹치는 일정만

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

    all_rows = seoul_rows + gwangjin_rows
    if all_rows:
        upsert("events", all_rows, on_conflict="source,title,start_date")
    print(f"총 {len(all_rows)}건 적재 완료 (V9 {len(seoul_rows)} + V10 {len(gwangjin_rows)})")


if __name__ == "__main__":
    load()