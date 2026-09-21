"""
T15 — 업종 상보성 점수 (S_complement, 명세서 3-3)

"""

# 소분류(category_s) 우선 매칭. "기타 간이"(I210) 소속 실제 값들.
# 값 = (S_complement, 「협업 업종 적합도 조사」 라벨) — 9/21 대표님 확정 점수/10.
COMPLEMENT_BY_SUB: dict[str, tuple[float, str]] = {
    # 제과·디저트 (8점) — 흑맥주와 페어링, 가족 손님 (대표님 메모)
    "빵/도넛": (0.8, "제과·디저트"),
    "떡/한과": (0.8, "제과·디저트"),  # 조사표 예시에 "떡집" 명시
    # 피자·치킨 (8점) — 테이크아웃 가능한 메뉴 (대표님 메모)
    "피자": (0.8, "피자·치킨"),
    "치킨": (0.8, "피자·치킨"),
    # 수제버거 (6점) — 조사표에 별도 항목으로 분리돼 있음
    "버거": (0.6, "수제버거"),
    # 분식 (8점) — 테이크아웃 가능한 메뉴 (대표님 메모)
    "김밥/만두/분식": (0.8, "분식"),
    # 토스트·샌드위치·샐러드 (5점) — 조사표에서 분식과 분리된 별도 항목
    "토스트/샌드위치/샐러드": (0.5, "토스트·샌드위치·샐러드"),
    # 아이스크림·빙수 (8점) — 조사표에서 카페와 분리된 별도 항목
    "아이스크림/빙수": (0.8, "아이스크림·빙수"),
    # 카페 (8점) — 비음주 손님용 (대표님 메모)
    "카페": (0.8, "카페"),
    # 주점 (5점) — 조사표 예시가 "생맥주집 등"으로 명시돼 있어 여기서 먼저 잡는다.
    # (9/15엔 "직접 경쟁"으로 보고 0.1을 줬었는데, 대표님 기준은 다르다 — 그대로 반영.)
    "생맥주 전문": (0.5, "주점"),
}

# 소분류가 표에 없을 때의 중분류 폴백.
COMPLEMENT_BY_MID: dict[str, tuple[float, str]] = {
    "비알코올": (0.8, "카페"),
    "한식": (0.5, "한식"),
    "중식": (0.5, "중식"),
    "일식": (0.5, "일식"),
    "서양식": (0.5, "양식"),
    "주점": (0.5, "주점"),  
}

# 화면(T24)의 업종 다중선택 필터 기본 옵션·표시 순서 — 조사표 순서를 따른다.
TIER_LABELS: list[str] = [
    "제과·디저트", "피자·치킨", "수제버거", "분식",
    "토스트·샌드위치·샐러드", "카페", "아이스크림·빙수",
    "한식", "중식", "일식", "양식", "주점",
]


def _lookup(category_m: str | None, category_s: str | None) -> tuple[float, str] | None:
    if category_s and category_s in COMPLEMENT_BY_SUB:
        return COMPLEMENT_BY_SUB[category_s]
    if category_m and category_m in COMPLEMENT_BY_MID:
        return COMPLEMENT_BY_MID[category_m]
    return None


def score_complement(category_m: str | None, category_s: str | None) -> float | None:
    """매핑에 없으면 None — 호출부에서 후보 제외 처리."""
    hit = _lookup(category_m, category_s)
    return hit[0] if hit else None


def tier_label(category_m: str | None, category_s: str | None) -> str:
    """화면 표시용 라벨. score_complement()와 같은 인자를 받는다 — 점수로
    역추정하지 않고 매핑 테이블에서 라벨을 직접 찾는다 (9/21 이전 방식은
    점수가 겹치면 라벨이 틀렸다 — 위 changelog 참조)."""
    hit = _lookup(category_m, category_s)
    return hit[1] if hit else "미분류"

_INDUSTRY_GUESS_BY_SUB = {
    "빵/도넛": "제과·디저트",
    "떡/한과": "제과·디저트",
    "피자": "피자·튀김·그릴",
    "치킨": "피자·튀김·그릴",
    "버거": "패스트푸드",
    "김밥/만두/분식": "분식·스낵",
    "토스트/샌드위치/샐러드": "분식·스낵",
    "아이스크림/빙수": "카페",
    "카페": "카페",
}
_INDUSTRY_GUESS_BY_MID = {
    "비알코올": "카페",
    "한식": "한식",
    "중식": "중식",
    "일식": "일식",
    "서양식": "양식",
}


def guess_industry_category(category_m: str | None, category_s: str | None) -> str:
    """INDUSTRY_MAP 키 중 하나를 추정해 돌려준다. 못 맞히면 '분식·스낵'
    (가장 무난한 기본값)으로 채워두고, 입력 폼에서 고치게 한다."""
    if category_s and category_s in _INDUSTRY_GUESS_BY_SUB:
        return _INDUSTRY_GUESS_BY_SUB[category_s]
    if category_m and category_m in _INDUSTRY_GUESS_BY_MID:
        return _INDUSTRY_GUESS_BY_MID[category_m]
    return "분식·스낵"