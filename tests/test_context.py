"""
컨텍스트 빌더 출력 확인 — T11 검증용

출력을 눈으로 보는 것에 더해, 기본 점검을 함께 수행한다.
이 문장이 (1) 상권분석가의 유일한 입력이므로 여기서 틀리면
이후 단계가 모두 틀린 전제 위에서 돌아간다.

실행: python -m tests.test_context
"""
import re
from datetime import date, datetime, timedelta, timezone

from context.builder import build, NO_DATA

KST = timezone(timedelta(hours=9))

# 있어야 할 구획
SECTIONS = ["[대상 시점]", "[실시간 인구]", "[12시간 예측]",
            "[실시간 상권]", "[날씨]", "[분기 매출 프로파일]", "[인근 행사"]

# 내부 계산값이 노출되면 안 된다 (예: "평균 2.6/4")
# LLM 이 해석할 맥락이 없어 판단에 쓰이지 못한다.
RAW_SCORE = re.compile(r"\d+\.\d+\s*/\s*\d+|평균\s*\d+\.\d+")

# 최고·최저 표기 줄 — 등급 이름이 반드시 함께 있어야 한다.
# "가장 혼잡"만 쓰면 실제로는 '여유' 수준인데도 붐비는 것으로 읽힌다.
EXTREME_LINE = re.compile(r"관측 구간 중 가장 (\S+)")

# 구간 표기 — 두 형식을 허용한다
#   최빈값 과반  : 06-11시 '여유' (6건 중 5건) / (6건 전부)
#   과반 미달    : 14-17시 관측 2건 — '붐빔' 1 / '보통' 1
BAND_GRADE = re.compile(r"^\s*(\d{2}-\d{2})시 (?:관측 \d+건 — )?'")

# 대표값 표기에서 근거 비율이 빠지면 안 된다
REP_GRADE = re.compile(r"'[^']+' \((\d+)건 (?:전부|중 (\d+)건)\)")

# 구간 간 차이가 없을 때의 표기
NO_DIFF = re.compile(r"시간대에 따른 (?:뚜렷한 )?차이")

# 등급 이름은 항상 작은따옴표로 감싼다.
# 이 표기가 없으면 "가장 혼잡"처럼 최상급만 남아 실제 수준을 알 수 없다.
HAS_GRADE = re.compile(r"'[^']+'")


def check(text: str) -> list[str]:
    """구조상 문제와 출력 원칙 위반을 잡는다. 값의 타당성은 눈으로 본다."""
    issues = []

    for sec in SECTIONS:
        if sec not in text:
            issues.append(f"구획 누락: {sec}")

    if "{" in text or "}" in text:
        issues.append("치환되지 않은 중괄호가 남아 있음")

    if "None" in text:
        issues.append("None 이 그대로 출력됨 — 빈 값 처리 누락")

    hits = RAW_SCORE.findall(text)
    if hits:
        issues.append(f"내부 계산값 노출: {hits[:3]} — 등급 이름으로 표기할 것")

    # 판단 근거 건수를 밝히는 것이 이번 설계의 핵심 원칙이다
    if "건 관측" not in text and "관측 " not in text:
        issues.append("관측 건수 표기 누락 — 판단 근거를 밝혀야 함")

    # 최고·최저 표기에 등급 이름이 빠지면 안 된다
    for line in text.splitlines():
        if EXTREME_LINE.search(line) and not BAND_GRADE.match(line):
            issues.append(f"등급 이름 누락: {line.strip()[:40]}")

    # 차이 없음 표기에도 등급 이름 또는 분포가 있어야 한다
    for line in text.splitlines():
        if NO_DIFF.search(line) and not HAS_GRADE.search(line):
            issues.append(f"등급 이름 누락: {line.strip()[:40]}")

    # 대표 등급은 최빈값이 과반일 때만 세운다.
    # 과반에 못 미치는데 대표값으로 표기되면 근거가 약한 단정이 된다.
    for m in REP_GRADE.finditer(text):
        total = int(m.group(1))
        top = int(m.group(2)) if m.group(2) else total
        if top * 2 <= total:
            issues.append(f"과반 미달인데 대표값 표기: {m.group(0)}")

    # 최고·최저의 대표 등급이 같으면 대비가 성립하지 않는다.
    # "'여유'인데 가장 혼잡"으로 읽혀 오해를 부른다.
    owner2 = None
    pair: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        if line.startswith("- "):
            owner2 = line[2:].split(":")[0].strip()
            continue
        # 대표값 형식일 때만 비교한다.
        # 분포 형식("관측 4건 — '분주한' 2 / '바쁜' 1 ...")은 대표 등급이 없으므로
        # 첫 등급을 대표값으로 오인하면 안 된다.
        e = EXTREME_LINE.search(line)
        g = REP_GRADE.search(line)
        if e and g and owner2 and not NO_DIFF.search(line):
            grade = g.group(0).split("'")[1]
            pair.setdefault(owner2, {})[e.group(1)] = grade
    for own, d in pair.items():
        if len(d) == 2 and len(set(d.values())) == 1:
            issues.append(f"대비 무의미: [{own}] 최고·최저 모두 '{next(iter(d.values()))}'")

    # 같은 항목 안에서 같은 구간이 최고이자 최저로 표기되면 대비가 무의미하다.
    # 서로 다른 항목(뚝섬역 / 한식 등)에서 같은 구간이 나오는 것은 정상이므로
    # 반드시 항목 단위로 묶어서 본다.
    owner = None
    per_owner: dict[str, dict[str, set]] = {}
    for line in text.splitlines():
        if line.startswith("- "):
            owner = line[2:].split(":")[0].strip()
            continue
        if NO_DIFF.search(line):
            continue
        m, e = BAND_GRADE.match(line), EXTREME_LINE.search(line)
        if m and e and owner:
            per_owner.setdefault(owner, {}).setdefault(m.group(1), set()).add(e.group(1))
    for own, bands in per_owner.items():
        for band, words in bands.items():
            if len(words) > 1:
                issues.append(
                    f"동일 구간 중복 표기: [{own}] {band}시가 {'·'.join(words)} 양쪽")

    n_empty = text.count(NO_DATA)
    if n_empty:
        issues.append(f"'{NO_DATA}' {n_empty}건 — 적재 대기 항목 확인 필요")

    return issues


def run(label: str, target: date) -> None:
    print("=" * 64)
    print(f"{label} — {target} ({['월','화','수','목','금','토','일'][target.weekday()]})")
    print("=" * 64)
    try:
        text = build(target)
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


if __name__ == "__main__":
    today = datetime.now(KST).date()
    friday = today + timedelta(days=(4 - today.weekday()) % 7)

    run("오늘", today)
    run("이번 주 금요일", friday)
    run("2차 점포 방문일", date(2026, 8, 31))
