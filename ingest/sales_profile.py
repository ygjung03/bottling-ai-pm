"""
분기 매출 프로파일 적재 — 서울시 상권분석서비스(추정매출-행정동)

[티켓] T08 / M3 (명세서 9-1)

원본은 서울 열린데이터광장의 「서울시 상권분석서비스(추정매출-행정동)」 CSV 한 장이다.
분기가 누적되어 들어오므로 새 분기가 나오면 같은 파일을 다시 받아 이 스크립트를
다시 돌리면 된다. UNIQUE(quarter, dong_code, industry_code) 로 upsert 한다.

실행: python -m ingest.sales_profile

[2026-09-08] 건수 비중을 함께 담는다.
  8/29 적재는 축별 비중을 매출 금액으로만 만들었다. 그래서 전체 객단가
  (sales_amount / sales_count)는 나와도 축별 객단가를 낼 수 없었다.
  원본에는 축마다 금액과 건수가 모두 있어 넣기만 하면 된다.

  구간 객단가 = (금액비중 × sales_amount) / (건수비중 × sales_count)

  이 값이 있어야 (2) 셰프가 판매가를, (4) 컨설턴트가 매입가를 정할 때
  "그 시간대 손님이 한 번에 얼마 쓰는가"를 근거로 쓸 수 있다.

[원칙] 축을 조합하지 않는다.
  원본이 요일·시간대·성별·연령을 각각 독립 합계로만 준다.
  "금요일 × 20대" 같은 행은 존재하지 않으므로 만들어내지 않는다 (명세서 2-4).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from db.client import upsert

CSV_PATH = Path("data/raw/sales_profile_행정동.csv")
DONG_NAMES = ["자양3동"]

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
GENDERS = {"남성": "남", "여성": "여"}
AGES = ["10", "20", "30", "40", "50", "60_이상"]

# 시간대는 금액과 건수의 컬럼명 규칙이 다르다.
#
# [주의] 원본 CSV 의 건수 컬럼명이 깨져 있다. 구간 시작값이 들어갈 자리에
#   "건수"가 박혀 있어 여섯 개가 아래처럼 온다.
#
#     시간대_건수~06_매출_건수   ← 00~06 이다
#     시간대_건수~11_매출_건수   ← 06~11
#     시간대_건수~14_매출_건수   ← 11~14
#     시간대_건수~17_매출_건수   ← 14~17
#     시간대_건수~21_매출_건수   ← 17~21
#     시간대_건수~24_매출_건수   ← 21~24
#
#   끝값(06·11·14·17·21·24)은 멀쩡하므로 그것으로 짝을 짓는다.
#   제공처가 고치면 이 매핑이 깨지므로, 없는 컬럼을 만나면 예외를 낸다.
TIMEBANDS = [
    # (저장 키,   금액 컬럼,                    건수 컬럼)
    ("00-06", "시간대_00~06_매출_금액", "시간대_건수~06_매출_건수"),
    ("06-11", "시간대_06~11_매출_금액", "시간대_건수~11_매출_건수"),
    ("11-14", "시간대_11~14_매출_금액", "시간대_건수~14_매출_건수"),
    ("14-17", "시간대_14~17_매출_금액", "시간대_건수~17_매출_건수"),
    ("17-21", "시간대_17~21_매출_금액", "시간대_건수~21_매출_건수"),
    ("21-24", "시간대_21~24_매출_금액", "시간대_건수~24_매출_건수"),
]


def to_quarter(code) -> str:
    """20262 → 2026Q2"""
    s = str(code)
    return f"{s[:4]}Q{s[4]}"


def _ratio(row, cols: dict[str, str], total) -> dict[str, float]:
    """
    축별 비중. total 이 0 이면 전부 0 으로 둔다.

    나눗셈을 건너뛰고 키를 빼지 않는다. 키가 없으면 관측이 0 인지 컬럼이
    누락된 것인지 구분되지 않아, 컨텍스트에서 같은 오해가 반복된다.
    """
    if not total:
        return {k: 0.0 for k in cols}
    return {k: round(float(row[c]) / float(total), 4) for k, c in cols.items()}


def load(csv_path: Path = CSV_PATH, dong_names: list[str] = DONG_NAMES) -> list[dict]:
    if not csv_path.exists():
        raise SystemExit(
            f"{csv_path} 가 없다.\n"
            "서울 열린데이터광장 「서울시 상권분석서비스(추정매출-행정동)」 CSV 를\n"
            "받아 그 경로에 두고 다시 실행할 것."
        )

    df = pd.read_csv(csv_path, encoding="cp949")

    # 컬럼명이 바뀌면 조용히 틀린 값이 들어가는 대신 여기서 멈춘다
    need = (["기준_년분기_코드", "행정동_코드", "행정동_코드_명",
             "서비스_업종_코드", "서비스_업종_코드_명",
             "당월_매출_금액", "당월_매출_건수"]
            + [f"{d}요일_매출_금액" for d in WEEKDAYS]
            + [f"{d}요일_매출_건수" for d in WEEKDAYS]
            + [c for _, a, b in TIMEBANDS for c in (a, b)]
            + [f"{g}_매출_금액" for g in GENDERS] + [f"{g}_매출_건수" for g in GENDERS]
            + [f"연령대_{a}_매출_금액" for a in AGES]
            + [f"연령대_{a}_매출_건수" for a in AGES])
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise SystemExit(f"원본에 없는 컬럼 {missing}\n컬럼명 규칙이 바뀌었는지 확인할 것.")

    df = df[df["행정동_코드_명"].isin(dong_names)]

    amt_cols = {
        "weekday": {d: f"{d}요일_매출_금액" for d in WEEKDAYS},
        "timeband": {k: a for k, a, _ in TIMEBANDS},
        "gender": {v: f"{g}_매출_금액" for g, v in GENDERS.items()},
        "age": {a: f"연령대_{a}_매출_금액" for a in AGES},
    }
    cnt_cols = {
        "weekday": {d: f"{d}요일_매출_건수" for d in WEEKDAYS},
        "timeband": {k: c for k, _, c in TIMEBANDS},
        "gender": {v: f"{g}_매출_건수" for g, v in GENDERS.items()},
        "age": {a: f"연령대_{a}_매출_건수" for a in AGES},
    }

    rows = []
    for _, r in df.iterrows():
        amt, cnt = int(r["당월_매출_금액"]), int(r["당월_매출_건수"])
        rows.append({
            "quarter": to_quarter(r["기준_년분기_코드"]),
            "dong_code": str(r["행정동_코드"]),
            "dong_name": r["행정동_코드_명"],
            "industry_code": str(r["서비스_업종_코드"]),
            "industry_name": r["서비스_업종_코드_명"],
            "sales_amount": amt,
            "sales_count": cnt,

            "weekday_ratio": _ratio(r, amt_cols["weekday"], amt),
            "timeband_ratio": _ratio(r, amt_cols["timeband"], amt),
            "gender_ratio": _ratio(r, amt_cols["gender"], amt),
            "age_ratio": _ratio(r, amt_cols["age"], amt),

            "weekday_count_ratio": _ratio(r, cnt_cols["weekday"], cnt),
            "timeband_count_ratio": _ratio(r, cnt_cols["timeband"], cnt),
            "gender_count_ratio": _ratio(r, cnt_cols["gender"], cnt),
            "age_count_ratio": _ratio(r, cnt_cols["age"], cnt),
        })

    upsert("sales_profile", rows, on_conflict="quarter,dong_code,industry_code")

    quarters = sorted({x["quarter"] for x in rows})
    print(f"{len(rows)}건 적재 완료 — {', '.join(dong_names)} / "
          f"{len(quarters)}개 분기 ({quarters[0]}~{quarters[-1]})")
    return rows


if __name__ == "__main__":
    load()
