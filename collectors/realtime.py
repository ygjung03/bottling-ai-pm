"""
서울 실시간 도시데이터 수집 — 뚝섬한강공원 · 뚝섬역

[담당] A
[주기] 30분 (GitHub Actions)
[중요] 이 API는 과거 조회가 불가능하다. 수집을 시작한 시점부터만 데이터가 쌓인다.

통합 API(citydata) 한 번 호출로 인구·상권·날씨를 모두 받는다.
지점당 1회, 총 2회 호출.

응답 구조
  CITYDATA
    LIVE_PPLTN_STTS [1]   인구·혼잡도·12시간 예측
    LIVE_CMRCL_STTS       상권 결제 (뚝섬한강공원은 None)
    WEATHER_STTS          날씨
    ... (교통·주차·지하철 등은 사용하지 않음)
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

from config.settings import SEOUL_API_KEY, SPOTS, RAW_DIR
from db.client import upsert

BASE = "http://openapi.seoul.go.kr:8088"
TIMEOUT = 30
KST = timezone(timedelta(hours=9))


# ---------- 형변환 ----------

def _int(v):
    """API가 숫자를 문자열로 주는 경우가 있다. '3000' -> 3000"""
    try:
        return int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _float(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _first(v):
    """리스트로 오기도 하고 dict로 오기도 하는 필드를 통일한다."""
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _kst(s):
    """'2026-08-22 19:45' -> ISO8601 (KST)"""
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y%m%d %H%M"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=KST).isoformat()
        except ValueError:
            continue
    return None


# ---------- 수집 ----------

def fetch(area_nm: str) -> dict:
    url = f"{BASE}/{SEOUL_API_KEY}/json/citydata/1/5/{area_nm}"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def save_raw(area_nm: str, payload: dict) -> None:
    """로컬 원본 백업. GitHub Actions에서는 실행 후 사라지므로 개발용."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    (RAW_DIR / f"citydata_{area_nm}_{ts}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------- 파싱 ----------

def _parse_ppltn(p: dict) -> dict:
    if not p:
        return {}
    return {
        "area_cd": p.get("AREA_CD"),
        "congestion_level": p.get("AREA_CONGEST_LVL"),
        "congestion_msg": p.get("AREA_CONGEST_MSG"),
        "population_min": _int(p.get("AREA_PPLTN_MIN")),
        "population_max": _int(p.get("AREA_PPLTN_MAX")),
        "ppltn_rates": {
            "male": _float(p.get("MALE_PPLTN_RATE")),
            "female": _float(p.get("FEMALE_PPLTN_RATE")),
            **{f"age_{a}": _float(p.get(f"PPLTN_RATE_{a}"))
               for a in (0, 10, 20, 30, 40, 50, 60, 70)},
            "resident": _float(p.get("RESNT_PPLTN_RATE")),
            "non_resident": _float(p.get("NON_RESNT_PPLTN_RATE")),
        },
        "forecast_12h": [
            {
                "time": _kst(f.get("FCST_TIME")),
                "level": f.get("FCST_CONGEST_LVL"),
                "min": _int(f.get("FCST_PPLTN_MIN")),
                "max": _int(f.get("FCST_PPLTN_MAX")),
            }
            for f in (p.get("FCST_PPLTN") or [])
        ],
        "_time": _kst(p.get("PPLTN_TIME")),
    }


def _parse_cmrcl(c: dict) -> dict:
    """뚝섬한강공원은 상권 데이터가 없어 None으로 온다."""
    if not c:
        return {}

    food = {}
    for r in (c.get("CMRCL_RSB") or []):
        if r.get("RSB_LRG_CTGR") != "음식·음료":
            continue
        food[r.get("RSB_MID_CTGR")] = {
            "level": r.get("RSB_PAYMENT_LVL"),
            "count": _int(r.get("RSB_SH_PAYMENT_CNT")),
            "amt_min": _int(r.get("RSB_SH_PAYMENT_AMT_MIN")),
            "amt_max": _int(r.get("RSB_SH_PAYMENT_AMT_MAX")),
            "store_cnt": _int(r.get("RSB_MCT_CNT")),
        }

    return {
        "cmrcl_level": c.get("AREA_CMRCL_LVL"),
        "pay_count": _int(c.get("AREA_SH_PAYMENT_CNT")),
        "pay_amt_min": _int(c.get("AREA_SH_PAYMENT_AMT_MIN")),
        "pay_amt_max": _int(c.get("AREA_SH_PAYMENT_AMT_MAX")),
        "food_pay": food or None,
        "cmrcl_rates": {
            "male": _float(c.get("CMRCL_MALE_RATE")),
            "female": _float(c.get("CMRCL_FEMALE_RATE")),
            **{f"age_{a}": _float(c.get(f"CMRCL_{a}_RATE"))
               for a in (10, 20, 30, 40, 50, 60)},
        },
    }


def _parse_weather(w: dict) -> dict:
    if not w:
        return {}
    return {
        "temp": _float(w.get("TEMP")),
        "humidity": _int(w.get("HUMIDITY")),
        "precpt_type": w.get("PRECPT_TYPE"),
        "pcp_msg": w.get("PCP_MSG"),
    }


def parse(area_nm: str, payload: dict) -> dict | None:
    city = payload.get("CITYDATA")
    if not city:
        code = payload.get("RESULT", {}).get("RESULT.CODE") or payload.get("RESULT.CODE")
        print(f"  CITYDATA 없음 (code={code})")
        return None

    ppltn = _parse_ppltn(_first(city.get("LIVE_PPLTN_STTS")))
    collected_at = ppltn.pop("_time", None) or datetime.now(KST).isoformat()

    row = {
        "collected_at": collected_at,
        "spot": area_nm,
        "raw": city,
    }
    row.update(ppltn)
    row.update(_parse_cmrcl(_first(city.get("LIVE_CMRCL_STTS"))))
    row.update(_parse_weather(_first(city.get("WEATHER_STTS"))))
    return row


# ---------- 실행 ----------

def main() -> None:
    rows = []
    for area_nm in SPOTS:
        try:
            payload = fetch(area_nm)
            if RAW_DIR.exists() or True:
                save_raw(area_nm, payload)
            row = parse(area_nm, payload)
            if row:
                rows.append(row)
                cm = "상권O" if row.get("cmrcl_level") else "상권X"
                print(f"[OK] {area_nm} {row['collected_at']} "
                      f"{row.get('congestion_level')} "
                      f"{row.get('population_min')}~{row.get('population_max')}명 {cm}")
            else:
                print(f"[SKIP] {area_nm}")
        except Exception as e:
            print(f"[FAIL] {area_nm}: {e}")

    if rows:
        upsert("market_context", rows, on_conflict="collected_at,spot")
        print(f"적재 {len(rows)}건")
    else:
        print("적재할 데이터 없음")


if __name__ == "__main__":
    main()
