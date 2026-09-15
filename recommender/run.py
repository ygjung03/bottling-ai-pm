"""
T15 — 추천 엔진 실행

1. nearby_stores 전체 조회
2. 프랜차이즈 추정 제외 (3-1, franchise.py) → 업종 매핑 안 되는 후보 제외 (3-2)
   — 두 제외 모두 건수 기록, 화면(T24)에도 표시할 것
3. 남은 후보 점수 계산 → score / score_detail 컬럼 갱신
   (제외된 후보는 score/score_detail을 명시적으로 비워, 이전 실행에서 남은
    값이 화면에 잘못 남지 않게 한다 — 아래 [주의] 참조)
4. 상위 10곳 출력 

실행: python -m recommender.run
선행: .env 에 SUPABASE_URL / SUPABASE_KEY 설정, T09(nearby_stores 적재) 완료.

 3-1 "프랜차이즈 추정 제외"를 franchise.py의 브랜드명 키워드
목록으로 구현했다. 결정 경위와 한계는 franchise.py 문서 참조.

[주의] 매 실행마다 전체 후보를 다시 upsert 한다 — score/score_detail이
있는 것만 보내면, 이번 실행에서 새로 제외된(예: 프랜차이즈 목록에 추가된)
후보의 이전 점수가 DB에 그대로 남아 화면(score IS NOT NULL 필터)에 계속
잡힌다. 그래서 제외된 후보도 score=None으로 명시적으로 함께 보낸다.

[주의] upsert 시 score/score_detail 두 컬럼만 보내면, 일부 행에서
postgrest 가 기존 행을 UPDATE 가 아니라 신규 INSERT 로 처리해
name 등 NOT NULL 컬럼이 비어 실패하는 경우가 있었다 (원인 미확정).
그래서 원본 행(name·category_l/m/s·distance_m)을 score 와 합쳐서
통째로 보낸다 — 진짜 UPDATE든 어쩌다 INSERT든 안전하다.
"""
from datetime import datetime, timezone

from db.client import get_client, upsert
from recommender.franchise import is_likely_franchise
from recommender.scoring import score_store


def fetch_all_stores() -> list[dict]:
    # db.client.select() 는 eq 필터만 지원해서 전체 조회는 여기서 직접 호출한다.
    res = (
        get_client()
        .table("nearby_stores")
        .select("store_id, name, category_l, category_m, category_s, address, lat, lng, distance_m")
        .execute()
    )
    return res.data


def list_unmapped(stores: list[dict]) -> None:
    """매핑표(complement.py)에 없는 category 조합을 건수 많은 순으로 보여준다.
    (프랜차이즈로 걸러지는 것과는 별개 — 업종 자체를 못 찾는 조합만 본다.)
    complement.py 의 매핑표를 실제 데이터에 맞게 채울 때 이걸 먼저 본다."""
    from collections import Counter

    from recommender.complement import score_complement

    unmapped = Counter()
    for s in stores:
        if score_complement(s.get("category_m"), s.get("category_s")) is None:
            unmapped[(s.get("category_l"), s.get("category_m"), s.get("category_s"))] += 1

    print(f"\n[매핑 확인] 매핑표에 없는 조합 {len(unmapped)}종 (건수 많은 순, 상위 30):")
    for (l, m, s), cnt in unmapped.most_common(30):
        print(f"  {cnt:>4}건  {l} > {m} > {s}")


def run():
    stores = fetch_all_stores()
    print(f"전체 후보(반경 1km): {len(stores)}건")

    list_unmapped(stores)

    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    scored: list[dict] = []
    excluded_franchise = 0
    excluded_unmapped = 0

    for s in stores:
        if is_likely_franchise(s.get("name")):
            excluded_franchise += 1
            rows.append({**s, "score": None, "score_detail": None, "updated_at": now})
            continue

        result = score_store(s)
        if result is None:
            excluded_unmapped += 1
            rows.append({**s, "score": None, "score_detail": None, "updated_at": now})
            continue

        scored.append(result)
        rows.append({
            **s,
            "score": result["score"],
            "score_detail": result["score_detail"],
            "updated_at": now,
        })

    print(
        f"\n매핑됨(점수 산출): {len(scored)}건 / "
        f"프랜차이즈 추정 제외(3-1): {excluded_franchise}건 / "
        f"업종 미매핑 제외(3-2): {excluded_unmapped}건"
    )
    print("※ 이 제외 건수는 3-1·3-2 원칙대로 T24 화면에도 그대로 노출할 것")

    upsert("nearby_stores", rows, on_conflict="store_id")
    print("score / score_detail 갱신 완료")

    top10 = sorted(scored, key=lambda x: x["score"], reverse=True)[:10]
    print("\n상위 10곳 (T16 — U5·U6 검토용):")
    for i, r in enumerate(top10, 1):
        print(
            f"  {i:>2}. {r['name']:<20} score={r['score']}  "
            f"{r['score_detail']}  ({r['distance_m']}m)"
        )
        print(f"      {r['reason']}")


if __name__ == "__main__":
    run()