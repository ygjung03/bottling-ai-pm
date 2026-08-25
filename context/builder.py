"""
컨텍스트 빌더 — DB 수치를 LLM이 읽을 문장으로 변환

[담당] B (집계 로직은 A와 공동)
[티켓] T11
[규격] 명세서 6-3

LLM 호출이 아닌 일반 코드다. 숫자 집계를 LLM에 맡기면 값이 부정확해진다.
이 출력이 (1) 상권분석가의 유일한 입력이므로, 여기서 틀리면 이후 단계가
모두 틀린 전제 위에서 돌아간다.

[출력 원칙]
  - 관측 사실을 그대로 제시한다. 표본이 적다는 이유로 항목을 생략하거나
    다른 값으로 대체하지 않는다. 건수를 밝히고 해석은 LLM 에 맡긴다
  - 대표 등급은 최빈값이 과반일 때만 세운다. 과반에 못 미치면 분포를 펼친다
    (건수가 아니라 흩어진 정도가 기준이다)
  - 내부 계산값(평균 2.6/4 등)을 노출하지 않는다.
    LLM 이 해석할 맥락이 없어 판단에 쓰이지 못한다.
    대신 어느 시간대가 어떠했는지를 등급 이름으로 제시한다
  - 판단 근거가 몇 건인지 함께 밝힌다
  - 없는 항목은 "데이터 없음"으로 명시. 누락하면 LLM이 지어낸다
  - 날씨 포함 (한강 상권에서 강수는 방문객을 좌우)
  - 상권 지표는 뚝섬역 기준임을 명시 (한강공원은 상권 데이터 없음)

[제외한 것]
  서울시 congestion_msg — 일반 시민용 안내라 자체 집계보다 정보량이 적고,
  어느 시점 문구인지 밝히면 문장만 길어진다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from collections import defaultdict

from db.client import get_client

KST = timezone(timedelta(hours=9))
NO_DATA = "데이터 없음"

PARK, STATION = "뚝섬한강공원", "뚝섬역"
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

# 혼잡도 4단계 → 순위 (평균 계산용)
CONGEST_RANK = {"여유": 1, "보통": 2, "약간 붐빔": 3, "붐빔": 4}
RANK_CONGEST = {v: k for k, v in CONGEST_RANK.items()}

# 결제 현황 4단계
PAY_RANK = {"한산한": 1, "보통": 2, "바쁜": 3, "분주한": 4}

# 시간대 구간 — sales_profile 의 timeband_ratio 와 동일한 6구간
TIMEBANDS = [(0, 6, "00-06"), (6, 11, "06-11"), (11, 14, "11-14"),
             (14, 17, "14-17"), (17, 21, "17-21"), (21, 24, "21-24")]


def _band(hour: int) -> str:
    for lo, hi, name in TIMEBANDS:
        if lo <= hour < hi:
            return name
    # TIMEBANDS 가 0~24 를 빈틈없이 덮으므로 도달하지 않는다.
    # 도달했다면 입력이 잘못된 것이므로 조용히 넘기지 않는다.
    raise ValueError(f"시간 범위 밖: {hour}")


def _grade_summary(levels: list[int], inv: dict[int, str]) -> str:
    """
    구간의 등급을 요약한다.

    평균을 내지 않는다. '보통'과 '붐빔'의 평균을 '약간 붐빔'으로 표기하면
    실제로 한 번도 관측되지 않은 등급이 출력된다.

    최빈값이 과반이면 대표 등급으로 요약하고, 과반에 못 미치면 분포를 펼친다.
    근거가 약한 대표값을 세우느니 실제 분포를 보이는 편이 판단에 도움이 된다.
    건수가 아니라 흩어진 정도를 기준으로 삼는다.
    """
    n = len(levels)
    cnt: dict[int, int] = defaultdict(int)
    for lv in levels:
        cnt[lv] += 1

    top = max(cnt, key=cnt.get)
    if cnt[top] * 2 > n:                       # 과반
        return (f"'{inv[top]}' ({n}건 전부)" if cnt[top] == n
                else f"'{inv[top]}' ({n}건 중 {cnt[top]}건)")

    parts = [f"'{inv[lv]}' {cnt[lv]}" for lv in sorted(cnt, reverse=True)]
    return f"관측 {n}건 — " + " / ".join(parts)


def _rep_grade(levels: list[int]) -> int | None:
    """최빈값이 과반일 때의 대표 등급. 과반이 아니면 None."""
    cnt: dict[int, int] = defaultdict(int)
    for lv in levels:
        cnt[lv] += 1
    top = max(cnt, key=cnt.get)
    return top if cnt[top] * 2 > len(levels) else None


def _band_rank(levels: list[int]) -> float:
    """구간 간 대소 비교용. 표시에는 쓰지 않는다."""
    return sum(levels) / len(levels)


def _band_extremes(pairs: list[tuple[int, int]], rank_map: dict[str, int],
                   hi_word: str, lo_word: str) -> list[str]:
    """
    (시각, 등급) 목록에서 가장 높은 구간과 낮은 구간을 제시한다.

    구간 간 순위는 평균으로 정하되, 표시되는 등급은 실제 관측값에서 가져온다.
    "가장 혼잡"처럼 상대적 위치만 밝히면, 실제 수준이 '보통'인데도 붐비는 것으로
    읽힐 수 있다. 등급 이름을 함께 표기한다.
    """
    by_band: dict[str, list[int]] = defaultdict(list)
    for h, lv in pairs:
        by_band[_band(h)].append(lv)
    if not by_band:
        return []

    inv = {v: k for k, v in rank_map.items()}
    rank = {b: _band_rank(v) for b, v in by_band.items()}

    if len(by_band) == 1:
        b = next(iter(by_band))
        return [f"{b}시에만 관측 — {_grade_summary(by_band[b], inv)}"]

    hi = max(rank, key=rank.get)
    lo = min(rank, key=rank.get)

    # 최고·최저 대비가 성립하지 않는 경우를 걸러낸다.
    #   (1) 구간별 평균이 모두 같음
    #   (2) 평균은 다르나 표시될 대표 등급이 같음
    #       예) 17-21시 평균 1.33 / 14-17시 평균 1.0 → 둘 다 '여유'로 표기된다.
    #           "'여유'인데 가장 혼잡"으로 읽혀 오해를 부른다.
    # "시간대에 따른 차이가 없다"는 것 자체가 판단 재료이므로 해당 내용을 서술한다.
    # (하루 종일 한산하다면 특정 시간을 노릴 이유가 없고,
    #  사람을 끌어올 이벤트가 필요하다는 뜻이 된다)
    g_hi, g_lo = _rep_grade(by_band[hi]), _rep_grade(by_band[lo])
    same_grade = g_hi is not None and g_hi == g_lo
    if rank[hi] == rank[lo] or same_grade:
        allv = [lv for v in by_band.values() for lv in v]
        n_band, n_obs = len(by_band), len(allv)
        kinds = {inv[lv] for lv in allv}
        if len(kinds) == 1:
            return [f"시간대에 따른 차이 없이 전 구간 '{kinds.pop()}'"
                    f" ({n_band}개 구간 {n_obs}건)"]
        cnt: dict[int, int] = defaultdict(int)
        for lv in allv:
            cnt[lv] += 1
        dist = " / ".join(f"'{inv[lv]}' {cnt[lv]}" for lv in sorted(cnt, reverse=True))
        return [f"시간대에 따른 뚜렷한 차이 없음"
                f" ({n_band}개 구간 {n_obs}건 — {dist})"]

    return [
        f"{hi}시 {_grade_summary(by_band[hi], inv)} — 관측 구간 중 가장 {hi_word}",
        f"{lo}시 {_grade_summary(by_band[lo], inv)} — 관측 구간 중 가장 {lo_word}",
    ]


def _band_dist(hours: list[int]) -> str:
    """시간대별 관측 건수를 사실 그대로 표기한다.

    구간별 관측 건수를 그대로 나열한다.
    어느 구간이 비어 있는지도 정보이므로 생략하지 않는다.
    """
    if not hours:
        return ""
    cnt = defaultdict(int)
    for h in hours:
        cnt[_band(h)] += 1
    parts = [f"{name} {cnt[name]}건"
             for _, _, name in TIMEBANDS if cnt.get(name)]
    return ", ".join(parts)


# ══════════════════════════════════════════
# 조회
# ══════════════════════════════════════════

def fetch_market(weeks: int = 4) -> list[dict]:
    """최근 N주 market_context 전체."""
    since = (datetime.now(KST) - timedelta(weeks=weeks)).isoformat()
    return (get_client().table("market_context")
            .select("*").gte("collected_at", since)
            .order("collected_at", desc=True).execute().data or [])


def fetch_sales(dong_name: str, industry: str | None = None) -> list[dict]:
    """sales_profile. A의 T08 적재 전에는 빈 리스트."""
    q = get_client().table("sales_profile").select("*").eq("dong_name", dong_name)
    if industry:
        q = q.eq("industry_name", industry)
    try:
        return q.execute().data or []
    except Exception:
        return []


def fetch_events(target: date, days: int = 30) -> list[dict]:
    """대상 시점 이후 N일 내 행사. A의 T10 적재 전에는 빈 리스트."""
    try:
        return (get_client().table("events").select("*")
                .gte("end_date", target.isoformat())
                .lte("start_date", (target + timedelta(days=days)).isoformat())
                .execute().data or [])
    except Exception:
        return []


# ══════════════════════════════════════════
# 집계
# ══════════════════════════════════════════

def _kst(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(KST)


def summarize_population(rows: list[dict], spot: str, target_dow: int) -> list[str]:
    """
    같은 요일의 관측 건수와 시간대 분포를 사실 그대로 제시한다.

    표본이 적다는 이유로 요일 필터를 풀거나 전체 평균으로 대체하지 않는다.
    전체 수집 기간이 4주 남짓이라 어떤 기준을 두어도 근거가 약하고,
    조건을 넘었다는 이유로 '금요일 피크는 19시' 같은 단정을 만들면 오히려 왜곡된다.
    표본 수와 분포를 그대로 주면 해석의 신중함은 LLM이 판단한다.
    """
    same = [r for r in rows
            if r["spot"] == spot and _kst(r["collected_at"]).weekday() == target_dow]
    if not same:
        return [f"- {spot}: 해당 요일 관측 {NO_DATA}"]

    hours = [_kst(r["collected_at"]).hour for r in same]
    dist = _band_dist(hours)

    lines = [f"- {spot}: {WEEKDAYS[target_dow]}요일 {len(same)}건 관측 ({dist})"]

    # 시간대별 혼잡 정도 — 최고·최저 구간
    pairs = [(_kst(r["collected_at"]).hour, CONGEST_RANK[r["congestion_level"]])
             for r in same if CONGEST_RANK.get(r.get("congestion_level"))]
    for line in _band_extremes(pairs, CONGEST_RANK, "혼잡", "한산"):
        lines.append(f"    {line}")
    return lines


def summarize_forecast(rows: list[dict], spot: str) -> list[str]:
    """가장 최근 수집분의 12시간 예측."""
    latest = next((r for r in rows if r["spot"] == spot and r.get("forecast_12h")), None)
    if not latest:
        return [f"- {NO_DATA}"]
    fc = latest["forecast_12h"][:6]          # 앞 6시간만
    parts = []
    for f in fc:
        t = f.get("time", "")[11:16]
        parts.append(f"{t} {f.get('level')}")
    return [f"- {spot}: " + " → ".join(parts)]


def summarize_commercial(rows: list[dict]) -> list[str]:
    """
    음식 중분류별 결제 현황.

    거래가 없는 카테고리는 응답에서 아예 빠진다. 따라서 '관측 건수'와
    '어느 시간대에 관측되었는지'를 함께 제시한다.
    관측률만으로는 언제 빠졌는지 알 수 없어 잘못된 추론을 유발한다.
    """
    st = [r for r in rows if r["spot"] == STATION and r.get("food_pay")]
    if not st:
        return [f"- {NO_DATA}"]

    recent = st[0]["food_pay"] or {}
    lv_by_cat: dict[str, list[int]] = defaultdict(list)
    hr_by_cat: dict[str, list[int]] = defaultdict(list)
    for r in st:
        h = _kst(r["collected_at"]).hour
        for cat, v in (r["food_pay"] or {}).items():
            lv = PAY_RANK.get(v.get("level"))
            if lv:
                lv_by_cat[cat].append(lv)
                hr_by_cat[cat].append(h)

    lines = [f"- 전체 관측 {len(st)}건 기준"]
    order = sorted(lv_by_cat,
                   key=lambda c: -sum(lv_by_cat[c]) / len(lv_by_cat[c]))
    for cat in order:
        n = len(lv_by_cat[cat])
        now = f"현재 '{recent[cat]['level']}'" if cat in recent else "현재 거래 없음"
        lines.append(f"- {cat}: {now}, 관측 {n}건")
        for line in _band_extremes(list(zip(hr_by_cat[cat], lv_by_cat[cat])),
                                   PAY_RANK, "분주", "한산"):
            lines.append(f"    {line}")
    return lines


def summarize_weather(rows: list[dict]) -> list[str]:
    latest = next((r for r in rows if r.get("temp") is not None), None)
    if not latest:
        return [f"- {NO_DATA}"]
    p = latest.get("precpt_type") or "정보 없음"
    hum = f", 습도 {latest['humidity']}%" if latest.get("humidity") else ""
    return [f"- 기온 {latest['temp']}도{hum}, 강수 {p}"]


def summarize_sales(dong: str, industry: str | None) -> list[str]:
    """sales_profile 축별 순위. 조합 데이터는 존재하지 않는다 (명세서 2-4)."""
    rows = fetch_sales(dong, industry)
    if not rows:
        return [f"- {NO_DATA} (적재 전)"]

    lines = []
    for r in rows[:3]:
        name = r.get("industry_name", "?")
        parts = []
        for label, key in [("요일", "weekday_ratio"), ("시간대", "timeband_ratio"),
                           ("연령", "age_ratio"), ("성별", "gender_ratio")]:
            d = r.get(key) or {}
            if not d:
                continue
            top = max(d, key=d.get)
            parts.append(f"{label} 최고 {top} {d[top]:.0%}")
        amt, cnt = r.get("sales_amount"), r.get("sales_count")
        unit = f", 객단가 {amt // cnt:,}원" if amt and cnt else ""
        lines.append(f"- {name}: " + " / ".join(parts) + unit)
    return lines or [f"- {NO_DATA}"]


def summarize_events(target: date) -> list[str]:
    evs = fetch_events(target)
    if not evs:
        return [f"- {NO_DATA}"]
    lines = []
    for e in evs[:5]:
        dist = f", 약 {e['distance_m']}m" if e.get("distance_m") else ""
        lines.append(f"- {e.get('title')} / {e.get('start_date')}～{e.get('end_date')}"
                     f" / {e.get('place')}{dist}")
    return lines


# ══════════════════════════════════════════
# 조립
# ══════════════════════════════════════════

def build(target: date, dong: str = "자양3동", industry: str | None = None) -> str:
    """(1) 상권분석가에 넣을 컨텍스트 문장을 만든다."""
    rows = fetch_market()
    dow = target.weekday()
    week = (target.day - 1) // 7 + 1

    sec = [
        f"[대상 시점] {target.year}년 {target.month}월 {week}주 {WEEKDAYS[dow]}요일",
        "",
        "[실시간 인구]",
        *summarize_population(rows, PARK, dow),
        *summarize_population(rows, STATION, dow),
        "",
        "[12시간 예측]",
        *summarize_forecast(rows, PARK),
        "",
        "[실시간 상권]  ※ 뚝섬역 기준 (뚝섬한강공원은 상권 데이터 없음)",
        *summarize_commercial(rows),
        "",
        "[날씨]",
        *summarize_weather(rows),
        "",
        f"[분기 매출 프로파일]  ※ {dong} 기준",
        *summarize_sales(dong, industry),
        "",
        "[인근 행사 (30일 내)]",
        *summarize_events(target),
    ]
    return "\n".join(sec)


if __name__ == "__main__":
    print(build(date.today()))
