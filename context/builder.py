"""
컨텍스트 빌더 — DB 수치를 LLM이 읽을 문장으로 변환

[담당] B (집계 로직은 A와 공동)
[티켓] T11
[규격] 명세서 6-3

LLM 호출이 아닌 일반 코드다. 숫자 집계를 LLM에 맡기면 값이 부정확해진다.
이 출력이 (1) 상권분석가의 유일한 입력이므로, 여기서 틀리면 이후 단계가
모두 틀린 전제 위에서 돌아간다.

[출력 원칙]
  - 대상 시점과 같은 요일만 집계한다. 인구·상권 모두 동일하다.
    요일을 섞으면 금요일 저녁과 화요일 저녁의 차이가 뭉개진다
  - 관측 사실을 그대로 제시한다. 표본이 적다는 이유로 항목을 생략하거나
    다른 값으로 대체하지 않는다. 건수를 밝히고 해석은 LLM 에 맡긴다
  - 대표 등급을 세우지 않는다. 4단계 분포를 항상 그대로 적는다
    (0건 등급도 생략하지 않는다. 누락과 구분되지 않아 오해를 부른다)
  - 내부 계산값(평균 2.6/4 등)을 노출하지 않는다.
    LLM 이 해석할 맥락이 없어 판단에 쓰이지 못한다
  - 상권은 같은 CMRCL_TIME 을 한 번만 센다. 인구는 5분, 상권은 10분
    주기로 갱신되는데 수집이 5분 간격이라 상권만 2배로 중복된다.
    새벽에는 결제가 없어 90～240분간 갱신되지 않아 최대 6.5배가 된다.
    거르지 않으면 2회 관측이 9건으로 집계되어 근거 건수가 무의미해진다
  - 판단 근거가 몇 건인지 함께 밝힌다
  - 방문객 구성(연령·성별·상주비율)도 혼잡도와 같은 6구간으로 쪼갠다.
    요일 전체로 묶으면 새벽과 저녁이 한 값이 되어 비상주 비율이
    19～65%처럼 벌어져 대표값이 아무것도 말하지 못한다.
    영업시간만 남기지도 않는다. 재료 납품은 시간대가 무관하고
    콘텐츠 촬영은 낮에 하므로, 어느 구간이 쓸모 있는지는 LLM이 정한다
  - 없는 항목은 "데이터 없음"으로 명시. 누락하면 LLM이 지어낸다
  - 날씨 포함 (한강 상권에서 강수는 방문객을 좌우)
  - 상권 지표는 뚝섬역 기준임을 명시 (한강공원은 상권 데이터 없음)

[제외한 것]
  서울시 congestion_msg — 일반 시민용 안내라 자체 집계보다 정보량이 적다.

  12시간 예측(forecast_12h) — 오늘 이후 12시간 예보다. 협업 기획은 며칠 뒤를
  대상으로 하므로 대상 시점과 무관한 값이 붙는다. 당일 즉흥 이벤트 기능이
  생기면 그때 다시 넣는다.

  카테고리별 현재 등급 — 가장 최근 시간 기준이라 협업 시점과 무관하다.
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
    구간의 등급 분포를 그대로 표기한다.

    평균을 내지 않는다. '보통'과 '붐빔'의 평균을 '약간 붐빔'으로 표기하면
    실제로 한 번도 관측되지 않은 등급이 출력된다.

    0건 등급도 생략하지 않는다. 언급이 없으면 관측이 0인지 항목 자체가
    누락된 것인지 구분되지 않아 오해를 부른다. 4단계를 항상 모두 적는다.
    """
    n = len(levels)
    cnt: dict[int, int] = defaultdict(int)
    for lv in levels:
        cnt[lv] += 1

    parts = [f"'{inv[lv]}' {cnt.get(lv, 0)}"
             for lv in sorted(inv, reverse=True)]
    return f"관측 {n}건 — " + " / ".join(parts)


def _band_lines(pairs: list[tuple[int, int]], rank_map: dict[str, int],
                hi_word: str, lo_word: str) -> list[str]:
    """
    관측된 전 구간의 등급 분포를 나열하고, 구간 간 순위를 참고로 덧붙인다.
    최고·최저 구간만 보여주면 나머지 구간의 분포가 버려진다.

    순위 판정은 코드가 계산해 (참고) 로 제시한다.
    집계를 코드가 맡아 값의 정확성을 보장하되(D3), 분포를 함께 제시해
    LLM 이 판정 근거를 직접 확인하고 판단할 수 있게 한다.
    """
    by_band: dict[str, list[int]] = defaultdict(list)
    for h, lv in pairs:
        by_band[_band(h)].append(lv)
    if not by_band:
        return []

    inv = {v: k for k, v in rank_map.items()}
    order = [name for _, _, name in TIMEBANDS if name in by_band]

    lines = [f"    {b}시 {_grade_summary(by_band[b], inv)}" for b in order]

    if len(by_band) < 2:
        return lines

    rank = {b: sum(v) / len(v) for b, v in by_band.items()}
    hi = max(rank, key=rank.get)
    lo = min(rank, key=rank.get)
    if rank[hi] == rank[lo]:
        lines.append("    (참고) 구간 간 평균 차이 없음")
    else:
        # 판정에 쓰인 구간의 관측 수를 함께 적는다.
        # 6건 평균과 17건 평균을 같은 자격으로 비교할 수 없으므로,
        # 순위와 근거 크기를 한 줄에 붙여 오해를 줄인다.
        lines.append(f"    (참고) 구간 평균 기준 가장 {hi_word} "
                     f"{hi}시({len(by_band[hi])}건)"
                     f" / 가장 {lo_word} {lo}시({len(by_band[lo])}건)")
    return lines


# ══════════════════════════════════════════
# 조회
# ══════════════════════════════════════════

# 조회할 컬럼.
#
# raw 를 통째로 받으면 안 된다. 행당 수십 KB 라 280행에 10 MB 를 넘고,
# 실측에서 select("*") 1.41초 / 10,535 KB 대 아래 조회 0.04초 / 142 KB 로
# 응답의 98.6% 가 raw 였다. 행이 쌓이면서 statement timeout(57014)이
# 실제로 발생하기 시작했다.
#
# raw 에서 필요한 것은 CMRCL_TIME 하나뿐이므로 PostgREST 의 JSONB
# 문법으로 그것만 뽑아 cmrcl_time 이라는 이름으로 받는다.
# LIVE_CMRCL_STTS 는 객체로 저장되어 있어 배열 인덱스(->0)를 쓰지 않는다.
COLUMNS = (
    "collected_at,spot,congestion_level,ppltn_rates,cmrcl_rates,"
    "food_pay,temp,humidity,precpt_type,"
    "cmrcl_time:raw->LIVE_CMRCL_STTS->>CMRCL_TIME"
)


def fetch_market(weeks: int = 4) -> list[dict]:
    """
    최근 N주 market_context.

    [주의] limit 을 명시하지 않으면 PostgREST 기본 상한(1,000행)에 걸린다.
      예외도 경고도 없이 결과만 조용히 잘리므로, 집계가 틀린 줄 모르고 쓰게 된다.
      2지점 × 하루 30～60건이면 3～4주 만에 상한에 닿아
      실측 구간(9～10월) 중에 반드시 도달한다.
    """
    since = (datetime.now(KST) - timedelta(weeks=weeks)).isoformat()
    return (get_client().table("market_context")
            .select(COLUMNS).gte("collected_at", since)
            .order("collected_at", desc=True)
            .limit(100000).execute().data or [])


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

    lines = [f"- {spot}: {WEEKDAYS[target_dow]}요일 {len(same)}건 관측"]

    # 시간대별 혼잡 정도 — 전 구간 분포 + (참고) 순위
    pairs = [(_kst(r["collected_at"]).hour, CONGEST_RANK[r["congestion_level"]])
             for r in same if CONGEST_RANK.get(r.get("congestion_level"))]
    lines += _band_lines(pairs, CONGEST_RANK, "혼잡", "한산")
    return lines


def _cmrcl_time(row: dict) -> str | None:
    """
    상권 데이터의 갱신 시각.

    수집기가 이 값을 파싱하지 않아 collected_at 에는 PPLTN_TIME 만 들어간다.
    별도 컬럼이 없으므로 조회 시 raw 에서 뽑아 온다(COLUMNS 참조).
    """
    return row.get("cmrcl_time")


def _dedup_cmrcl(rows: list[dict]) -> list[dict]:
    """
    같은 CMRCL_TIME 을 한 번만 남긴다.

    인구는 5분, 상권은 10분 주기로 갱신되는데(서울시 공식) 수집은 5분
    간격이므로 상권 값이 정확히 2배로 저장된다. 새벽에는 결제가 없어
    90～240분간 갱신되지 않아 최대 6.5배까지 중복된다.

    걸러내지 않으면 '보통' 2회 관측이 9건으로 집계되어, 근거 건수를
    함께 밝히는 이 파일의 규칙 자체가 무의미해진다.

    CMRCL_TIME 이 없는 행은 판단할 수 없으므로 남긴다. 지우면 실제
    관측을 잃지만, 남기면 최악의 경우 중복이 하나 섞이는 데 그친다.
    """
    seen: set[str] = set()
    out = []
    for r in rows:
        t = _cmrcl_time(r)
        if t is None:
            out.append(r)
            continue
        if t not in seen:
            seen.add(t)
            out.append(r)
    return out


def summarize_commercial(rows: list[dict], target_dow: int) -> list[str]:
    """
    음식 중분류별 결제 현황.

    인구와 동일하게 대상 시점과 같은 요일만 집계한다.
    금요일 저녁의 결제 양상과 화요일 저녁은 다르므로, 요일을 섞으면
    둘 중 어느 쪽도 아닌 값이 나온다.

    같은 CMRCL_TIME 은 한 번만 센다. 갱신 주기가 인구보다 길어
    거르지 않으면 표본이 2～6.5배로 부풀려진다.

    거래가 없는 카테고리는 응답에서 아예 빠진다. 따라서 '관측 건수'와
    '어느 시간대에 관측되었는지'를 함께 제시한다.
    관측률만으로는 언제 빠졌는지 알 수 없어 잘못된 추론을 유발한다.
    """
    st = _dedup_cmrcl([r for r in rows
                       if r["spot"] == STATION and r.get("food_pay")
                       and _kst(r["collected_at"]).weekday() == target_dow])
    if not st:
        return [f"- 해당 요일 관측 {NO_DATA}"]

    lv_by_cat: dict[str, list[int]] = defaultdict(list)
    hr_by_cat: dict[str, list[int]] = defaultdict(list)
    for r in st:
        h = _kst(r["collected_at"]).hour
        for cat, v in (r["food_pay"] or {}).items():
            lv = PAY_RANK.get(v.get("level"))
            if lv:
                lv_by_cat[cat].append(lv)
                hr_by_cat[cat].append(h)

    lines = [f"- {WEEKDAYS[target_dow]}요일 {len(st)}건 관측"]
    order = sorted(lv_by_cat,
                   key=lambda c: -sum(lv_by_cat[c]) / len(lv_by_cat[c]))
    for cat in order:
        n = len(lv_by_cat[cat])
        lines.append(f"- {cat}: 관측 {n}건")
        lines += _band_lines(list(zip(hr_by_cat[cat], lv_by_cat[cat])),
                             PAY_RANK, "분주", "한산")
    return lines


def _pct(vals: list[float]) -> tuple[int, int, int, int] | None:
    """
    비율값의 평균·최소·최대와 유효 관측 수를 돌려준다.

    평균을 쓴다. 연령대마다 중앙값을 따로 내면 서로 다른 회차의 값이
    섞여 합이 61%나 101%가 된다. 각 회차의 합이 100 이므로
    평균의 합은 항상 100 이 되어 비중으로 읽을 수 있다.

    평균은 이상치에 끌려가지만, 그 이상치는 관측이 적어서가 아니라
    결제 자체가 1～2건이라 생긴다. 관측을 늘려도 사라지지 않으므로
    감추는 대신 결제 건수를 함께 밝혀 판단을 맡긴다.

    유효 수를 함께 돌려주는 이유는, 전체 관측 중 몇 건이 실제로 계산에
    쓰였는지 밝히기 위해서다. None 인 행이 빠진 것을 모르면 몇 건으로
    낸 값인지 알 수 없다.
    """
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    return round(sum(v) / len(v)), round(v[0]), round(v[-1]), len(v)


def _top_ages(rows: list[dict], key: str, prefix: str, top: int = 3) -> str | None:
    """
    연령 비중 상위 N개를 큰 순서로 적는다.

    8구간(0～70대)을 모두 적으면 길기만 하고 읽히지 않는다.
    상위 3개면 방문객의 주축이 드러나고, 나머지는 합계로 묶어
    생략이 아니라 집계임을 밝힌다.
    """
    avg: dict[int, int] = {}
    for a in (0, 10, 20, 30, 40, 50, 60, 70):
        got = _pct([(r.get(key) or {}).get(f"{prefix}{a}") for r in rows])
        if got:
            avg[a] = got[0]
    if not avg:
        return None

    order = sorted(avg, key=lambda a: -avg[a])
    parts = [f"{a}대 {avg[a]}%" for a in order[:top]]
    rest = sum(avg[a] for a in order[top:])
    if rest:
        parts.append(f"그 외 합 {rest}%")
    return " / ".join(parts)


def _pay_total(rows: list[dict]) -> str:
    """
    구간의 결제 건수 합계. 소비 비중이 몇 건에 근거한 값인지 밝힌다.

    업종별 범위(5～11건)로 적지 않는다. 소비 비중 자체가 업종
    구분 없는 지점 전체 값이기 때문이다.
    """
    total = sum(v["count"] for r in rows
                for v in (r.get("food_pay") or {}).values()
                if v.get("count") is not None)
    return f"  (결제 {total}건)" if total else ""


def _visitor_line(rows: list[dict], key: str, prefix: str,
                  label: str, indent: str, total: int) -> list[str]:
    """
    한 구간의 연령·성별 한 묶음.

    total 은 이 구간의 전체 관측 수다. _pct 가 센 유효 수(n)가 그보다
    적으면 값이 없는 행이 섞여 있었다는 뜻이므로 n/total 을 함께 적는다.

    현재 데이터에서는 필드가 통째로 오거나 통째로 빠져 아직 발동한 적이
    없다. 남의 API 이므로 언제 일부만 빠질지 알 수 없어 남겨둔다.
    """
    out = []
    age = _top_ages(rows, key, prefix)
    if age:
        out.append(f"{indent}{label}연령 {age}")

    male = _pct([(r.get(key) or {}).get("male") for r in rows])
    if male:
        mid, _, _, n = male
        note = f" (유효 {n}/{total}건)" if n < total else ""
        out.append(f"{indent}{label}성별 남 {mid}% / 여 {100 - mid}%{note}")
    return out


def summarize_visitors(rows: list[dict], spot: str, target_dow: int) -> list[str]:
    """
    방문객 구성 — 시간대별 상주 비율, 연령·성별, 소비 연령·성별.

    혼잡도와 같은 6구간으로 쪼갠다. 요일 전체로 묶으면 새벽과 저녁이
    한 값이 되어 비상주 비율이 19～65% 처럼 벌어졌다.
    그 폭이면 대표값 하나로는 아무것도 말하지 못한다.

    영업시간(15시 이후)만 남기지 않는 이유는, 협력사 사정이 다르기
    때문이다. 재료 납품은 시간대가 무관하고 콘텐츠 촬영은 낮에 한다.
    어느 구간이 쓸모 있는지는 코드가 아니라 LLM 이 판단한다.

    인구 비중과 소비 비중을 나란히 적는다. 뚝섬역에서 40대는
    인구 16% / 소비 31% 로 엇갈리는데, 한쪽만 보면 이것이 보이지 않는다.
    """
    same = [r for r in rows
            if r["spot"] == spot and _kst(r["collected_at"]).weekday() == target_dow]
    if not same:
        return [f"- {spot}: 해당 요일 관측 {NO_DATA}"]

    by_band: dict[str, list[dict]] = defaultdict(list)
    for r in same:
        by_band[_band(_kst(r["collected_at"]).hour)].append(r)

    lines = [f"- {spot}: {WEEKDAYS[target_dow]}요일 {len(same)}건 관측"]

    for name in [n for _, _, n in TIMEBANDS if n in by_band]:
        grp = by_band[name]
        n_obs = len(grp)
        lines.append(f"    {name}시 관측 {n_obs}건")

        nr = _pct([(r.get("ppltn_rates") or {}).get("non_resident") for r in grp])
        if nr:
            mid, lo, hi, _ = nr
            span = f" (범위 {lo}～{hi}%)" if lo != hi else ""
            lines.append(f"        비상주 {mid}%{span}")

        lines += _visitor_line(grp, "ppltn_rates", "age_", "", " " * 8, n_obs)

        # 소비 구성은 상권 데이터가 있는 지점에만 존재한다.
        # 상권은 갱신 주기가 길어 같은 값이 반복 저장되므로,
        # CMRCL_TIME 으로 걸러야 실제 관측 수에 근거한 평균이 나온다.
        cm = _dedup_cmrcl([r for r in grp if r.get("cmrcl_rates")])
        if cm:
            out = _visitor_line(cm, "cmrcl_rates", "age_", "소비 ",
                                " " * 8, len(cm))
            if out:
                out[0] += _pay_total(cm)
            lines.append(f"        (소비는 {n_obs}건 중 상권 갱신 {len(cm)}건 기준)")
            lines += out

    return lines


def summarize_weather(rows: list[dict]) -> list[str]:
    """
    가장 최근 수집분의 날씨.

    [한계] 대상 시점의 날씨가 아니다.
      협업 기획은 며칠~몇 주 뒤를 대상으로 하므로, 최근 관측치를 그대로
      제시하면 그 시점 날씨로 오해될 수 있다.

    [예정] 기상청 단기예보 API 연동
      대상 시점의 예보를 조회해 대체한다. 한강 상권에서 강수 여부는
      방문객 수를 좌우하므로 실제 예보가 필요하다.
      단기예보는 3일, 중기예보는 10일까지 제공되므로 그보다 먼 시점은
      과거 같은 시기 평년값으로 보완하거나 "예보 범위 밖"으로 표기한다.
    """
    latest = next((r for r in rows if r.get("temp") is not None), None)
    if not latest:
        return [f"- {NO_DATA}"]
    p = latest.get("precpt_type") or "정보 없음"
    hum = f", 습도 {latest['humidity']}%" if latest.get("humidity") else ""
    when = _kst(latest["collected_at"]).strftime("%m/%d %H시")
    return [f"- 기온 {latest['temp']}도{hum}, 강수 {p}",
            f"  ※ {when} 관측치. 대상 시점의 예보가 아님"]


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
        f"[실시간 인구]  ※ {WEEKDAYS[dow]}요일 관측분",
        *summarize_population(rows, PARK, dow),
        *summarize_population(rows, STATION, dow),
        "",
        f"[실시간 상권]  ※ 뚝섬역 기준, {WEEKDAYS[dow]}요일 관측분"
        f" (뚝섬한강공원은 상권 데이터 없음)",
        *summarize_commercial(rows, dow),
        "",
        f"[방문객 구성]  ※ {WEEKDAYS[dow]}요일 관측분"
        f" — 각 비율은 관측 평균. '소비'는 결제 기준으로 인구 비중과 별개",
        *summarize_visitors(rows, PARK, dow),
        *summarize_visitors(rows, STATION, dow),
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
