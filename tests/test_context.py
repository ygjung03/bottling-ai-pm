"""
컨텍스트 빌더 출력 확인 — T11 검증용

출력을 눈으로 보는 것에 더해, 구조와 원칙 위반을 함께 점검한다.
이 문장이 (1) 상권분석가의 유일한 입력이므로 여기서 틀리면
이후 단계가 모두 틀린 전제 위에서 돌아간다.

실행: python -m tests.test_context
"""
import re
from datetime import date, datetime, timedelta, timezone

from chain.inputs import fetch_partner
from context.builder import build, fetch_market, NO_DATA, _kst

KST = timezone(timedelta(hours=9))

# 있어야 할 구획
SECTIONS = ["[대상 시점]", "[실시간 인구]", "[실시간 상권]", "[방문객 구성]",
            "[날씨]", "[분기 매출 프로파일]", "[인근 행사"]

# 인구·상권 모두 대상 시점과 같은 요일만 집계한다.
# 섹션 제목에 요일이 명시되어야 집계 범위를 오해하지 않는다.
DOW_MARK = re.compile(r"※ .*?[월화수목금토일]요일 관측분")

# 연령 비중 줄. 상위 3개 + "그 외 합" 형태이며 합이 100 이어야 한다.
#
# 연령대마다 중앙값을 따로 내면 서로 다른 회차의 값이 섞여
# 합이 61% 나 101% 가 된다. 평균으로 바꾼 뒤 합이 100 이 되었으므로,
# 다시 벗어나면 집계 방식이 되돌아간 것이다.
AGE_LINE = re.compile(r"(소비 )?연령 ((?:\d+대|그 외 합) \d+%"
                      r"(?: / (?:\d+대|그 외 합) \d+%)*)")
AGE_ITEM = re.compile(r"(?:\d+대|그 외 합) (\d+)%")

# 소비는 인구와 표본이 다르다. 상권 갱신 주기가 길어 중복을 걷어내면
# 구간 관측 수보다 적어진다. 그 사실을 밝히지 않으면 같은 근거로 읽힌다.
CONSUME_BASE = re.compile(r"\(소비는 (\d+)건 중 상권 갱신 (\d+)건 기준\)")

# 날씨는 최근 관측치이지 대상 시점의 예보가 아니다.
# 그 사실을 밝히지 않으면 해당 시점 날씨로 오해된다. (U12 연동 전까지)
WEATHER_NOTE = re.compile(r"관측치\. 대상 시점의 예보가 아님")

# 내부 계산값이 노출되면 안 된다 (예: "평균 2.6/4")
# LLM 이 해석할 맥락이 없어 판단에 쓰이지 못한다.
RAW_SCORE = re.compile(r"\d+\.\d+\s*/\s*\d+|평균\s*\d+\.\d+")

# 구간 분포 표기 — 4단계를 항상 모두 적는다
DIST_LINE = re.compile(r"(\d{2}-\d{2})시 관측 (\d+)건 — ((?:'[^']+' \d+(?: / )?)+)")

# 코드가 낸 판정은 (참고) 로 분리해 제시한다
REF_LINE = re.compile(r"\(참고\)")

# 판정성 표현. (참고) 밖에 나오면 코드가 결론을 서술한 것이다.
VERDICT = re.compile(r"가장 (?:혼잡|한산|분주)|차이 없음|전 구간")

# (참고) 순위 줄에는 판정 근거가 된 관측 건수를 함께 적는다.
# 6건 평균과 17건 평균을 같은 자격으로 비교할 수 없다.
REF_RANK = re.compile(r"\(참고\) 구간 평균 기준 가장 \S+ (\d{2}-\d{2})시\((\d+)건\)"
                      r" / 가장 \S+ (\d{2}-\d{2})시\((\d+)건\)")
REF_ANY_RANK = re.compile(r"\(참고\) 구간 평균 기준")


def check(text: str) -> list[str]:
    """구조상 문제와 출력 원칙 위반을 잡는다. 값의 타당성은 눈으로 본다."""
    issues = []

    for sec in SECTIONS:
        if sec not in text:
            issues.append(f"구획 누락: {sec}")

    # 인구·상권 섹션에 집계 요일이 표시되어야 한다
    for line in text.splitlines():
        if line.startswith("[실시간 인구]") or line.startswith("[실시간 상권]"):
            if not DOW_MARK.search(line):
                issues.append(f"집계 요일 미표시: {line.strip()[:40]}")

    # 날씨에 관측 시점 단서가 있어야 한다
    if "기온" in text and not WEATHER_NOTE.search(text):
        issues.append("날씨 출처 미표시 — 최근 관측치임을 밝혀야 함")

    if "{" in text or "}" in text:
        issues.append("치환되지 않은 중괄호가 남아 있음")

    if "None" in text:
        issues.append("None 이 그대로 출력됨 — 빈 값 처리 누락")

    hits = RAW_SCORE.findall(text)
    if hits:
        issues.append(f"내부 계산값 노출: {hits[:3]} — 등급 이름으로 표기할 것")

    # 판단 근거 건수를 밝히는 것이 핵심 원칙이다
    if "건 관측" not in text and "관측 " not in text:
        issues.append("관측 건수 표기 누락 — 판단 근거를 밝혀야 함")

    # 4단계를 모두 적어야 한다.
    # 0건 등급을 생략하면 관측이 0인지 항목이 누락된 것인지 구분되지 않는다.
    for m in DIST_LINE.finditer(text):
        band, total = m.group(1), int(m.group(2))
        grades = re.findall(r"'([^']+)' (\d+)", m.group(3))
        if len(grades) != 4:
            issues.append(f"{band}시 등급 4단계 미표기 ({len(grades)}개)")
        s_cnt = sum(int(c) for _, c in grades)
        if s_cnt != total:
            issues.append(f"{band}시 건수 불일치 (분포 합 {s_cnt} vs 표기 {total})")

    # 코드가 결론을 문장으로 내면 안 된다. (참고) 로만 제시한다.
    for line in text.splitlines():
        if VERDICT.search(line) and not REF_LINE.search(line):
            issues.append(f"코드가 결론 서술: {line.strip()[:40]}")

    # (참고) 순위 줄에 관측 건수가 빠지면 표본 크기를 알 수 없다.
    for line in text.splitlines():
        if REF_ANY_RANK.search(line) and not REF_RANK.search(line):
            issues.append(f"(참고) 순위에 관측 건수 누락: {line.strip()[:50]}")

    # 연령 비중의 합이 100 에서 벗어나면 집계 방식이 되돌아간 것이다.
    #
    # 각 회차의 비중 합이 100 이므로 평균의 합도 100 이 된다.
    # 다만 항목마다 정수로 반올림하므로 항목당 최대 0.5 의 오차가 생긴다.
    # 연령은 최대 8구간(0～70대)이라 이론상 96～104 를 벗어날 수 없다.
    for m in AGE_LINE.finditer(text):
        total = sum(int(v) for v in AGE_ITEM.findall(m.group(2)))
        if not 96 <= total <= 104:
            kind = "소비 연령" if m.group(1) else "연령"
            issues.append(f"{kind} 비중 합 {total}% — 평균이 아닌 방식으로 집계됨")

    # 소비 표본은 중복을 걷어낸 값이므로 구간 관측 수를 넘을 수 없다.
    for m in CONSUME_BASE.finditer(text):
        n_obs, n_cm = int(m.group(1)), int(m.group(2))
        if n_cm > n_obs:
            issues.append(f"소비 표본이 관측 수 초과 ({n_cm} > {n_obs})")

    # 소비 줄은 반드시 표본 표기를 동반해야 한다.
    # 인구와 근거 크기가 다른데 밝히지 않으면 같은 자격으로 읽힌다.
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "소비 연령" not in line:
            continue
        prev = lines[i - 1] if i else ""
        if not CONSUME_BASE.search(prev):
            issues.append(f"소비 표본 표기 누락: {line.strip()[:40]}")

    n_empty = text.count(NO_DATA)
    if n_empty:
        issues.append(f"'{NO_DATA}' {n_empty}건 — 적재 대기 항목 확인 필요")

    return issues


def run(label: str, target: date) -> None:
    print("=" * 64)
    print(f"{label} — {target} ({['월','화','수','목','금','토','일'][target.weekday()]})")
    print("=" * 64)
    try:
        # 협력사 업종에 맞는 매출 프로파일을 싣는다.
        # 넘기지 않으면 바틀링 업종만 실려 상대 업종을 볼 수 없다.
        partner = fetch_partner()
        text = build(target,
                     partner_category=(partner or {}).get("category"))
    except Exception as e:
        print(f"  실패: {e}")
        return

    print(text)

    issues = check(text)
    print()
    print("-" * 64)
    print(f"길이 {len(text)}자 / {len(text.splitlines())}줄")
    if issues:
        for i in issues:
            print(f"  · {i}")
    else:
        print("  구조 이상 없음")
    print()


def busiest_weekday_date() -> tuple[date, int]:
    """
    수집분이 가장 많은 요일의 가장 최근 날짜를 찾는다.

    오늘 날짜로 확인하면 요일에 따라 출력이 비어 있을 수 있어
    형식을 제대로 볼 수 없다. 데이터가 있는 요일로 확인한다.

    주의: DB 상태에 따라 결과가 달라지므로 재현성이 없다.
          어느 요일을 골랐는지 함께 출력한다.
    """
    rows = fetch_market()
    if not rows:
        return datetime.now(KST).date(), 0
    cnt: dict[int, int] = {}
    for r in rows:
        dow = _kst(r["collected_at"]).weekday()
        cnt[dow] = cnt.get(dow, 0) + 1
    best = max(cnt, key=cnt.get)
    today = datetime.now(KST).date()
    back = (today.weekday() - best) % 7
    return today - timedelta(days=back), cnt[best]


if __name__ == "__main__":
    today = datetime.now(KST).date()
    friday = today + timedelta(days=(4 - today.weekday()) % 7)
    busy, n = busiest_weekday_date()

    run(f"수집분이 가장 많은 요일 ({n}건)", busy)
    run("이번 주 금요일", friday)
    run("2차 점포 방문일", date(2026, 8, 31))
