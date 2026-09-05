"""
T09 — 반경 점포 적재 (nearby_stores)

호출 규격 (검증 완료, API검증결과.md V8 참조):
GET https://apis.data.go.kr/B553077/api/open/sdsc2/storeListInRadius
    cx=127.0679483 & cy=37.5318919 & radius=1000
    & indsLclsCd=I2 & numOfRows=1000 & pageNo=1 & type=json

540건 확인됨, numOfRows=1000이라 페이징 불필요.
"""

import math
import os

import requests
from dotenv import load_dotenv

from db.client import upsert

load_dotenv()

API_URL = "https://apis.data.go.kr/B553077/api/open/sdsc2/storeListInRadius"

BOTTLING_LAT = float(os.getenv("BOTTLING_LAT", "37.5318919"))
BOTTLING_LNG = float(os.getenv("BOTTLING_LNG", "127.0679483"))


def haversine_m(lat1, lng1, lat2, lng2):
    """두 좌표 사이 거리(미터)."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fetch_stores(radius=1000, inds_lcls_cd="I2"):
    key = os.getenv("DATA_GO_KR_KEY")
    if not key:
        raise RuntimeError("DATA_GO_KR_KEY 가 .env 에 설정되지 않았습니다.")

    params = {
        "serviceKey": key,
        "cx": BOTTLING_LNG,
        "cy": BOTTLING_LAT,
        "radius": radius,
        "indsLclsCd": inds_lcls_cd,
        "numOfRows": 1000,
        "pageNo": 1,
        "type": "json",
    }
    r = requests.get(API_URL, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    body = data.get("body", {})
    items = body.get("items", [])
    total = body.get("totalCount", len(items))
    if total > len(items):
        # 방어적 처리 — V8 검증 시점엔 540 < 1000 이라 발생하지 않았지만
        # 향후 반경을 넓히면 페이징이 필요해질 수 있음
        print(f"[경고] totalCount({total}) > 수신 건수({len(items)}) — 페이징 로직 추가 필요")

    return items


def load(radius=1000, inds_lcls_cd="I2"):
    items = fetch_stores(radius=radius, inds_lcls_cd=inds_lcls_cd)
    print(f"수신: {len(items)}건")

    rows = []
    for it in items:
        lat = it.get("lat")
        lng = it.get("lon")
        distance_m = None
        if lat is not None and lng is not None:
            distance_m = round(haversine_m(BOTTLING_LAT, BOTTLING_LNG, lat, lng))

        address = it.get("rdnmAdr") or it.get("lnoAdr") or None

        rows.append({
            "store_id": it.get("bizesId"),
            "name": it.get("bizesNm"),
            "category_l": it.get("indsLclsNm"),
            "category_m": it.get("indsMclsNm"),
            "category_s": it.get("indsSclsNm"),
            "address": address,
            "lat": lat,
            "lng": lng,
            "distance_m": distance_m,
            # score / score_detail 은 추천엔진(T15)에서 채움 — 여기선 비워둠
        })

    upsert("nearby_stores", rows, on_conflict="store_id")
    print(f"{len(rows)}건 적재 완료")


if __name__ == "__main__":
    load()