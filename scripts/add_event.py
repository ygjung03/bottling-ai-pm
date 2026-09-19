"""
행사 한 건을 손으로 넣는다 — 수집기가 못 잡는 행사용

[담당] B

[임시 경로다] 행사 수집을 네이버 검색 API(뉴스·블로그)나 제미나이 검색으로
  보강하기 전까지만 쓴다. 그것이 붙으면 이 스크립트는 지운다.
  (docs/private/남은_작업_0917.md 「행사 수집 보강」)

왜 필요한가: 서울시 API 는 장기 전시 위주고, 광진구청 주간 안내글은 다음 주
것까지만 올라온다. 그래서 10/9 드론쇼처럼 몇 주 뒤 행사는 기획안을 만들
시점엔 어느 쪽에도 없다. 그런 행사는 주최 측 공지를 사람이 확인해 넣는다.

지어내지 않는다 — 공지에 적힌 것만 넣고 출처 URL 을 남긴다.

실행: python -m scripts.add_event --apply
"""
import math
import sys

from db.client import get_client

# 바틀링 (API검증결과 V8 실측)
BOTTLING = (37.5318919, 127.0679483)
# 뚝섬한강공원 (서울시 citydata 의 장소 좌표. 정확한 위치는 공원 안 어디냐에 따라 다르다)
PARK = (37.5299, 127.0699)

# 출처: https://www.seouldroneshow.com/announcements (2026-09-19 확인)
#   기간 9.12(토)~10.31(토), 장소 뚝섬한강공원
#   2회차 10. 9. (금)
#   19:30~20:30 문화예술공연(1부) / 20:30~20:45 드론 라이트 쇼 /
#   20:45~20:55 미니 드론 쇼 / 20:55~21:25 문화예술공연(2부)
#   우천·강풍 시 취소 또는 지연 가능
EVENT = {
    "source": "manual",
    "title": "2026 한강 불빛 공연(드론 라이트 쇼) 2회차 — 19:30~21:25, 드론쇼 20:30~20:45",
    "place": "뚝섬한강공원",
    "start_date": "2026-10-09",
    "end_date": "2026-10-09",
    "lat": PARK[0],
    "lng": PARK[1],
    "is_free": True,       # 무료 (사용자 확인, 2026-09-19)
    "url": "https://www.seouldroneshow.com/announcements",
}


def haversine_m(a, b) -> int:
    r = 6371000
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(r * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h)))


def main() -> None:
    row = {**EVENT, "distance_m": haversine_m(BOTTLING, PARK)}
    for k, v in row.items():
        print(f"  {k:12} {v}")

    cli = get_client()
    cur = (cli.table("events").select("id")
           .eq("source", row["source"]).eq("title", row["title"])
           .eq("start_date", row["start_date"]).execute().data or [])
    if cur:
        print(f"\n이미 있다 (id={cur[0]['id']}). 중단.")
        return
    if "--apply" not in sys.argv:
        print("\n--apply 를 붙이면 넣는다.")
        return
    cli.table("events").insert(row).execute()
    print("\n넣었다.")


if __name__ == "__main__":
    main()
