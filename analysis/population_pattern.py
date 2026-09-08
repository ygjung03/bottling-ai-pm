"""T25 준비 — 뚝섬 상권 요일×시간대 인구 패턴 분석

market_context에 30분 주기로 누적된 인구 데이터를 요일×시간대로 집계해서
- 지점별 히트맵 이미지 (PNG) 저장
- 콘솔에 핵심 수치 요약 출력 (보고서 문장 쓸 때 그대로 인용 가능)

사용법:
    python -m analysis.population_pattern
    (또는 analysis/ 폴더가 없으면 그냥 리포지토리 루트에서 python population_pattern.py)

출력:
    population_heatmap_뚝섬한강공원.png
    population_heatmap_뚝섬역.png
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")  # 화면 없이 파일로만 저장
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from db.client import get_client

SPOTS = ["뚝섬한강공원", "뚝섬역"]
WEEKDAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"]
PAGE_SIZE = 1000


def fetch_all(spot):
    """market_context 전체를 페이지 단위로 수신 (기본 limit 우회)."""
    client = get_client()
    rows = []
    start = 0
    while True:
        end = start + PAGE_SIZE - 1
        res = (
            client.table("market_context")
            .select("collected_at,population_min,population_max")
            .eq("spot", spot)
            .order("collected_at", desc=False)
            .range(start, end)
            .execute()
        )
        chunk = res.data or []
        rows.extend(chunk)
        if len(chunk) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    return pd.DataFrame(rows)


def to_kst(series_utc):
    return (
        pd.to_datetime(series_utc, utc=True)
        .dt.tz_convert("Asia/Seoul")
    )


def analyze_spot(spot):
    df = fetch_all(spot)
    if df.empty:
        print(f"[{spot}] 데이터 없음 — 건너뜀")
        return None

    df["collected_kst"] = to_kst(df["collected_at"])
    df["mid"] = (df["population_min"] + df["population_max"]) / 2
    df["weekday"] = df["collected_kst"].dt.weekday  # 0=월
    df["hour"] = df["collected_kst"].dt.hour

    span_days = (df["collected_kst"].max() - df["collected_kst"].min()).days + 1
    print(f"\n=== {spot} ===")
    print(f"수집 기간: {df['collected_kst'].min():%Y-%m-%d %H:%M} ~ {df['collected_kst'].max():%Y-%m-%d %H:%M} "
          f"({span_days}일, {len(df)}건)")

    # 요일 x 시간대 피벗 (평균 추정 인구)
    pivot = df.pivot_table(index="weekday", columns="hour", values="mid", aggfunc="mean")
    pivot = pivot.reindex(index=range(7))  # 월~일 순서 고정, 데이터 없는 요일도 행 유지

    # 핵심 수치 — 보고서에 바로 쓸 수 있는 형태
    hourly_avg = df.groupby("hour")["mid"].mean()
    peak_hour = hourly_avg.idxmax()
    quiet_hour = hourly_avg.idxmin()

    weekday_avg = df.groupby("weekday")["mid"].mean()
    weekend_mask = df["weekday"] >= 5
    weekday_mean = df.loc[~weekend_mask, "mid"].mean()
    weekend_mean = df.loc[weekend_mask, "mid"].mean()
    diff_pct = (weekend_mean - weekday_mean) / weekday_mean * 100 if weekday_mean else float("nan")

    print(f"시간대 피크: {peak_hour}시 (평균 {hourly_avg[peak_hour]:,.0f}명) / "
          f"한산: {quiet_hour}시 (평균 {hourly_avg[quiet_hour]:,.0f}명)")
    print(f"평일 평균 {weekday_mean:,.0f}명 vs 주말 평균 {weekend_mean:,.0f}명 "
          f"({'+' if diff_pct >= 0 else ''}{diff_pct:.1f}%)")
    if weekday_avg.notna().sum() == 7:
        best_day = WEEKDAY_LABELS[weekday_avg.idxmax()]
        worst_day = WEEKDAY_LABELS[weekday_avg.idxmin()]
        print(f"요일 중 최고: {best_day}요일, 최저: {worst_day}요일")
    else:
        missing = [WEEKDAY_LABELS[d] for d in range(7) if pd.isna(weekday_avg.get(d))]
        print(f"아직 데이터 없는 요일: {', '.join(missing)} — 표본 부족 구간이니 보고서에 명시할 것")

    # 히트맵 이미지
    fig, ax = plt.subplots(figsize=(10, 4.5))
    im = ax.imshow(pivot.values, aspect="auto", cmap="YlOrRd")
    ax.set_yticks(range(7))
    ax.set_yticklabels(WEEKDAY_LABELS)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h}시" for h in range(0, 24, 2)])
    ax.set_title(f"{spot} — 요일×시간대 추정 인구 (평균)")
    cbar = fig.colorbar(im, ax=ax, shrink=0.85)
    cbar.set_label("추정 인구 (명)")
    fig.tight_layout()

    out_path = ROOT / f"population_heatmap_{spot}.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"저장: {out_path.name}")

    return pivot


def main():
    for spot in SPOTS:
        analyze_spot(spot)


if __name__ == "__main__":
    main()