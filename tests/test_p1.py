"""
(1) 상권분석가 프롬프트 확인 — T12 검증용

실제 컨텍스트 빌더 출력을 넣어 (1)만 단독 실행한다.
체인 전체를 돌리기 전에 첫 단계가 데이터를 제대로 읽는지 본다.

실행: python -m tests.test_p1
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

from chain.gemini import call
from chain.loader import build
from context.builder import build as build_context, fetch_market, _kst

KST = timezone(timedelta(hours=9))

# 요일별 영업시간 — 월요일 휴무
HOURS = {0: None, 1: (15, 23), 2: (15, 23), 3: (15, 22.5),
         4: (15, 22.5), 5: (15, 22.5), 6: (15, 22.5)}

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

# 컨텍스트에 등장할 수 있는 등급 이름 전부.
# 이 밖의 표현이 근거로 인용되면 지어낸 것이다.
GRADES = {"여유", "보통", "약간 붐빔", "붐빔",
          "한산한", "바쁜", "분주한"}

# 근거 지표가 입력을 인용했다고 볼 수 있는 형태.
#
# 대부분은 등급 이름이나 관측 건수를 담지만, 날씨와 방문객 구성도
# 판단 근거가 된다. 이 줄들에는 따옴표도 "건"도 없어
# 인정 대상에 넣지 않으면 정상 인용을 오탐으로 잡는다.
CITED = [
    re.compile(r"'"),                      # 등급 이름
    re.compile(r"\d+\s*건"),               # 관측·결제 건수
    re.compile(r"기온|습도|강수"),          # 날씨
    re.compile(r"비상주|연령|성별"),        # 방문객 구성
]


def _hhmm(v: str) -> float | None:
    m = re.match(r"(\d{1,2}):(\d{2})", str(v))
    return int(m.group(1)) + int(m.group(2)) / 60 if m else None


def check(out: dict, ctx: str, target: date) -> list[str]:
    """프롬프트가 지시한 제약을 지켰는지 본다."""
    issues = []
    slots = out.get("공략_시간대") or []
    biz = HOURS[target.weekday()]

    # 월요일은 휴무이므로 공략 시간대를 비워야 한다
    if biz is None:
        if slots:
            issues.append(f"휴무일인데 공략 시간대 제시: {len(slots)}개")
        if not out.get("주의사항"):
            issues.append("휴무 사실을 주의사항에 기록하지 않음")
        return issues

    if not slots:
        issues.append("공략 시간대 없음")

    open_h, close_h = biz
    for s in slots:
        st, en = _hhmm(s.get("시작", "")), _hhmm(s.get("종료", ""))
        if st is not None and st < open_h:
            issues.append(f"개점 전 시간대: {s.get('시작')}")
        if en is not None and en > close_h:
            issues.append(f"마감 후 시간대: {s.get('종료')}")
        if not s.get("근거_건수"):
            issues.append(f"근거 건수 누락: {s.get('시작')}")

    # 근거 지표는 원문을 인용해야 한다
    for g in out.get("근거_지표") or []:
        if not any(p.search(g) for p in CITED):
            issues.append(f"원문 인용 없는 근거: {g[:30]}")

    # 입력에 없는 등급 이름을 만들어내면 안 된다
    for g in out.get("근거_지표") or []:
        for q in re.findall(r"'([^']+)'", g):
            if q not in ctx:
                kind = "등급" if q in GRADES else "표현"
                issues.append(f"입력에 없는 {kind} 인용: '{q}'")

    if not out.get("주의사항"):
        issues.append("주의사항 없음 — 표본 한계를 기록해야 함")

    return issues


def latest_weekday(dow: int) -> date:
    """가장 최근에 지나간 해당 요일. 오늘이 그 요일이면 오늘."""
    today = datetime.now(KST).date()
    return today - timedelta(days=(today.weekday() - dow) % 7)


def weekday_counts() -> dict[int, int]:
    """요일별 수집 건수. 표본 크기를 함께 보기 위한 것이다."""
    cnt: dict[int, int] = {}
    for r in fetch_market() or []:
        d = _kst(r["collected_at"]).weekday()
        cnt[d] = cnt.get(d, 0) + 1
    return cnt


def run(label: str, target: date) -> None:
    dow = WEEKDAYS[target.weekday()]
    print("=" * 64)
    print(f"{label} — {target} ({dow})")
    print("=" * 64)

    ctx = build_context(target)
    prompt = build("p1_analyst", context=ctx, target_date=target.isoformat())
    print(f"프롬프트 {len(prompt)}자 (컨텍스트 {len(ctx)}자)\n")

    try:
        out, ms = call(prompt)
    except Exception as e:
        print(f"실패: {e}\n")
        return

    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n소요 {ms/1000:.1f}초")

    issues = check(out, ctx, target)
    print("-" * 64)
    if issues:
        for i in issues:
            print(f"  · {i}")
    else:
        print("  제약 위반 없음")
    print()


if __name__ == "__main__":
    cnt = weekday_counts()

    # 영업일 두 개로 실제 시간대 선정 판단을 본다.
    # 월요일은 휴무라 공략 시간대가 비므로 그 판단이 검증되지 않는다.
    for dow in (1, 3):
        d = latest_weekday(dow)
        run(f"{WEEKDAYS[dow]}요일 ({cnt.get(dow, 0)}건 수집)", d)

    # 휴무일 처리는 이미 확인했으나 회귀 방지로 남겨둔다
    run("2차 점포 방문일 — 휴무일 처리 확인", date(2026, 8, 31))
