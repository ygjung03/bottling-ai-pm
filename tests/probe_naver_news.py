"""
네이버 뉴스 행사 검색 — 어느 단계에서 기사가 빠지는지 확인용

    python -m tests.probe_naver_news

검색어마다, 정렬(sim 관련도 / date 최신) 별로
    받은 건수 → 지역 키워드 탈락 → 날짜 못 뽑음 → 기간 밖 → 채택
을 세고, 각 탈락 단계의 제목을 몇 개씩 보여준다.

"""
from collections import Counter
from datetime import date, datetime, timedelta

import requests

from config.settings import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
from ingest.events import (LOCATION_KEYWORDS, LOOKAHEAD_DAYS, NEWS_URL,
                           _strip_html, extract_event_dates)

QUERIES = [
    # 지금 쓰는 것
    "뚝섬 드론쇼", "뚝섬한강공원 축제", "뚝섬한강공원 행사",
    "자양동 축제", "광진구 축제", "한강공원 페스티벌 뚝섬",
    # 새로 시험해 볼 것
    "뚝섬 페스티벌", "뚝섬 공연", "뚝섬 마켓", "뚝섬 플리마켓",
    "한강 축제 10월", "한강 축제 11월", "광진구 행사", "성수 축제",
    "건대 축제", "뚝섬 불꽃",
]
EXTRA_KEYWORDS = ["광진", "성수", "건대", "구의", "뚝섬유원지"]
SHOW = 3   # 단계마다 보여줄 제목 수


def search(q, sort):
    r = requests.get(NEWS_URL, timeout=15,
                     headers={"X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
                              "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET},
                     params={"query": q, "display": 100, "sort": sort})
    r.raise_for_status()
    return r.json().get("items", [])


def judge(it, keywords, today, horizon):
    title = _strip_html(it.get("title", ""))
    text = f"{title} {_strip_html(it.get('description', ''))}"
    if not any(k in text for k in keywords):
        return "지역탈락", title
    pub = datetime.strptime(it["pubDate"], "%a, %d %b %Y %H:%M:%S %z").date()
    s, e = extract_event_dates(text, pub)
    if not s:
        return "날짜없음", title
    if e < today or s > horizon:
        return "기간밖", f"{s}~{e}  {title}"
    return "채택", f"{s}~{e}  {title}"


def main():
    today = date.today()
    horizon = today + timedelta(days=LOOKAHEAD_DAYS)
    wide = LOCATION_KEYWORDS + EXTRA_KEYWORDS

    for q in QUERIES:
        for sort in ("sim", "date"):
            items = search(q, sort)
            base = Counter()
            samples = {}
            for it in items:
                verdict, line = judge(it, LOCATION_KEYWORDS, today, horizon)
                base[verdict] += 1
                samples.setdefault(verdict, []).append(line)
            wide_ok = sum(judge(it, wide, today, horizon)[0] == "채택" for it in items)

            print(f"\n[{q} / {sort}] 받음 {len(items)} · 지역탈락 {base['지역탈락']} · "
                  f"날짜없음 {base['날짜없음']} · 기간밖 {base['기간밖']} · "
                  f"채택 {base['채택']} (지역 넓히면 {wide_ok})")
            for verdict in ("채택", "기간밖", "날짜없음"):
                for line in samples.get(verdict, [])[:SHOW]:
                    print(f"    {verdict:4} {line}")


if __name__ == "__main__":
    main()