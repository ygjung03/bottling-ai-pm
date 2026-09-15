"""
T15 — 업종 상보성 점수 (S_complement, 명세서 3-3)

[9/15 수정] 처음 넣었던 소분류 이름(제과점/치킨전문점/분식전문점 등)은
sales_profile.industry_name 기준으로 추측한 것이었는데, 실제 nearby_stores
데이터(소상공인시장진흥공단 상가정보 API)의 category_s 표기와 달라
전혀 매칭되지 않았다. 아래는 run.py 로 실제 뽑아본 값 기준으로 고친 것.

이전엔 COMPLEMENT_BY_MID 의 "기타 간이": 1.0 폴백이 전부를 흡수해서
피자·치킨·빵도넛·토스트·버거·분식이 죄다 1.0으로 찍히는 문제 발생.
그 폴백을 없애고 소분류별로 분류.

[9/15 확정] 아래 세 그룹은 명세서 3-3 표에 없어 직접 판단해 확정. 확인 요망.
 U5·U6(가중치·매핑표 대표님 최종 확정)는 명세서
9장 기준 W5~W7(실증 구간)에 대표님과 다시 검토하는 항목이라, 여기 값은
"확정"이 아니라 "그때까지 쓰는 잠정값". 실제 순위가 거리순에 너무
가깝다고 판단되면 그 시점에 항목 추가 — 지금은 넣지 않는다. 
"""

# 소분류(category_s) 우선 매칭. "기타 간이"(I210) 소속 실제 값들.
COMPLEMENT_BY_SUB: dict[str, float] = {
    # 제과·디저트 (1.0) — 기존 협업 실적 있음, 완제품 매입 용이
    "빵/도넛": 1.0,
    "떡/한과": 1.0,  # 명세서 3-3 원문에 "붕어빵, 떡, 베이커리"로 명시됨
    # 피자·튀김·그릴 (0.9) — 맥주 페어링 적합
    "피자": 0.9,
    "치킨": 0.9,
    "버거": 0.9,  # 사유 : 그릴 조리·맥주 페어링 궁합이 피자·치킨과 같은 결
    # 분식·스낵 (0.8) — 간편 조합
    "김밥/만두/분식": 0.8,
    "토스트/샌드위치/샐러드": 0.8,  # 사유 : 즉석 완제품 성격이 분식류에 가까움
    "아이스크림/빙수": 0.6,  # 사유 : 제과 정의와 달라 카페 쪽에 배정 — 논알콜 라인 연계
    # 카페 (0.6)
    "카페": 0.6,
    # 한식·중식 (0.4) — 좌석 중심, 테이크아웃 전환 난이도
    # (개별 소분류가 너무 많고 세분화 의미가 없어 중분류로 처리 — 아래 COMPLEMENT_BY_MID 참조)
    # 주류 판매점 (0.1) — 직접 경쟁
    "생맥주 전문": 0.1,
}

# 소분류가 표에 없을 때의 중분류 폴백.
COMPLEMENT_BY_MID: dict[str, float] = {
    "비알코올": 0.6,   # 카페
    "한식": 0.4,
    "중식": 0.4,
    "일식": 0.4,       # 산정 이유 : "좌석 중심·테이크아웃 전환 난이도" 논리를 한식·중식과 동일 적용
    "서양식": 0.4,     #  산정 이유 : 위와 동일
    "주점": 0.1,       # 요리 주점·일반 유흥 주점 등 — 직접 경쟁으로 판단
    # "그 외 기타 간이 음식점"(8건)·"동남아시아"(9건)·"구내식당·뷔페"(1건)는
    # 의도적으로 제외 상태 유지. 업종 성격을 구체적으로 특정할 수 없어
    # (특히 "그 외 기타"는 정의상 무엇이든 될 수 있다) 점수를 매기면 근거 없는
    # 값이 순위에 섞이므로 후보 화면에는 제외 건수로만 노출.
}


def score_complement(category_m: str | None, category_s: str | None) -> float | None:
    """매핑에 없으면 None — 호출부에서 후보 제외 처리."""
    if category_s and category_s in COMPLEMENT_BY_SUB:
        return COMPLEMENT_BY_SUB[category_s]
    if category_m and category_m in COMPLEMENT_BY_MID:
        return COMPLEMENT_BY_MID[category_m]
    return None


# 명세서 3-3 여섯 구간 표시용 라벨 (T24 화면 — 표·필터·지도 범례에 쓴다)
TIER_LABEL = {
    1.0: "제과·디저트",
    0.9: "피자·튀김·그릴",
    0.8: "분식·스낵",
    0.6: "카페",
    0.4: "한식·중식류",
    0.1: "주류 판매점",
}


def tier_label(s_complement: float | None) -> str:
    if s_complement is None:
        return "미분류"
    return TIER_LABEL.get(min(TIER_LABEL, key=lambda k: abs(k - s_complement)), "미분류")


# context/builder.py 의 INDUSTRY_MAP 키로 변환 — 협력사 초대(T24) 시 category
# 컬럼 초기값을 채우는 용도다. INDUSTRY_MAP 은 sales_profile 업종명과 연결되는
# 값이라 이 표의 6구간과 1:1로 안 맞는다 (예: 일식·서양식은 원래 3-3에 없음).
# 여기서 만든 값은 어디까지나 미리 채우는 추정치이고, 1_협력사_입력.py 폼에서
# 얼마든지 고칠 수 있다.
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