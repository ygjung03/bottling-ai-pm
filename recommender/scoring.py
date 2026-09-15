"""
T15 — 점수 산출 (명세서 3-2, 3-4)

Score = 0.50·S_distance + 0.50·S_complement

"""
from recommender.complement import score_complement

RADIUS_M = 1000


def score_distance(distance_m: int) -> float:
    return max(0.0, 1 - (distance_m / RADIUS_M))


def score_store(store: dict) -> dict | None:
    """
    store: nearby_stores 한 행 (store_id, name, category_l/m/s, distance_m 포함).
    매핑 안 되는 업종이거나 거리 정보가 없으면 None.
    """
    s_complement = score_complement(store.get("category_m"), store.get("category_s"))
    if s_complement is None:
        return None

    distance_m = store.get("distance_m")
    if distance_m is None:
        return None

    s_distance = round(score_distance(distance_m), 3)
    score = round(0.5 * s_distance + 0.5 * s_complement, 3)

    industry_label = store.get("category_s") or store.get("category_m") or "미상 업종"
    walk_min = round(distance_m / 67)  # 도보 약 67m/분 근사치. 필요시 조정.
    reason = f"도보 약 {walk_min}분 거리의 {industry_label}으로 완제품 매입이 용이합니다."

    naver_map_url = f"https://map.naver.com/p/search/{store.get('name', '')}"

    return {
        "store_id": store["store_id"],
        "name": store.get("name"),
        "distance_m": distance_m,
        "score": score,
        "score_detail": {"S_distance": s_distance, "S_complement": s_complement},
        "reason": reason,
        "naver_map_url": naver_map_url,
    }
