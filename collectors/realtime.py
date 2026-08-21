"""
서울 실시간 도시데이터 수집 — 뚝섬한강공원 · 뚝섬역

[담당] A
[주기] 30분 (GitHub Actions)
[중요] 이 API는 과거 조회가 불가능하다. 수집을 시작한 시점부터만 데이터가 쌓인다.

현 단계에서는 응답 원본을 raw 컬럼에 통째로 저장한다.
필드 파싱(parse_*)은 실제 응답 구조를 확인한 뒤 채운다.
"""
import json
from datetime import datetime, timezone

import requests

from config.settings import SEOUL_API_KEY, SPOTS, RAW_DIR
from db.client import upsert

BASE = "http://openapi.seoul.go.kr:8088"
TIMEOUT = 20


def fetch(spot_name: str) -> dict:
    """한 장소 조회. API가 1회 1장소만 지원한다."""
    url = f"{BASE}/{SEOUL_API_KEY}/json/citydata/1/5/{spot_name}"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def save_raw(spot_name: str, payload: dict) -> None:
    """로컬 원본 백업. 파싱 로직을 짤 때 참고용."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = RAW_DIR / f"realtime_{spot_name}_{ts}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse(spot_name: str, payload: dict) -> dict:
    """
    TODO(A): 실제 응답 구조 확인 후 채울 것.

    확인 대상
      - 혼잡도 등급 문자열의 실제 값
      - 인구 범위가 min/max 두 값인지
      - 12시간 예측이 배열인지, 몇 개 단위인지
      - 음식 대분류가 단독 필드로 오는지
      - 결제금액 단위(원/천원)

    collected_at 은 반드시 API 응답에 찍힌 시각을 쓴다.
    GitHub Actions 크론은 5~15분 밀리므로 예정 시각을 쓰면 시계열이 어긋난다.
    """
    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),  # TODO: 응답 시각으로 교체
        "spot": spot_name,
        "congestion_level": None,
        "population_min": None,
        "population_max": None,
        "forecast_12h": None,
        "food_pay_amount": None,
        "food_pay_count": None,
        "commercial_level": None,
        "raw": payload,
    }


def main() -> None:
    rows = []
    for spot_name in SPOTS:
        try:
            payload = fetch(spot_name)
            save_raw(spot_name, payload)
            rows.append(parse(spot_name, payload))
            print(f"[OK] {spot_name}")
        except Exception as e:
            print(f"[FAIL] {spot_name}: {e}")

    if rows:
        upsert("market_context", rows, on_conflict="collected_at,spot")
        print(f"적재 {len(rows)}건")
    else:
        print("적재할 데이터 없음")


if __name__ == "__main__":
    main()
