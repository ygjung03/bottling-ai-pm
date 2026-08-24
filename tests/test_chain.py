"""
체인 실행기 동작 확인 — SDK 교체 후 검증용

chain/runner.py 가 실제로 도는지 최소 데이터로 확인한다.
실행: python -m tests.test_chain
"""
import json
import time

from chain.runner import run

# 최소 입력 (실제 데이터 없이 구조만 확인)
ARGS = dict(
    context="[대상 시점] 2026년 9월 3주 금요일\n[실시간 인구]\n- 뚝섬한강공원: 금요일 평균 '붐빔', 피크 18~21시\n[날씨]\n- 기온 23도, 강수 없음",
    target_date="2026-09-18",
    beer_list="바틀링 라거 12원/ml 라거 / 갈매기 IPA 20원/ml IPA / 워터멜론 위트에일 20원/ml 위트에일",
    kitchen="전자레인지·에어프라이어만 가능. 화기 불가. 5분 넘는 조리 불가",
    partner_res="떡붕 / 제과·디저트 / 붕어빵 / 식재료: 팥앙금, 슈크림, 반죽 / 장비: 붕어빵 기계(이동 가능)",
    partner_blockers="주말 출장 불가 / 반죽 당일 소진",
    constraints="- 준비 기간은 3일 이내로 제안한다.\n- 예상 원가는 판매가의 40%를 넘지 않는다.",
    fewshot="(없음)",
    bottling_sns="팔로워 2400명 / 릴스 위주",
    partner_sns="팔로워 3200명 / 릴스 위주",
    events="(없음)",
    rec_reason="도보 5분 제과업. 이동식 조리 가능. 점수 0.784",
)


def on_step(n, label):
    print(f"  ({n}) {label}")


if __name__ == "__main__":
    print("체인 실행 시작\n")
    t0 = time.perf_counter()
    try:
        r = run(on_step=on_step, **ARGS)
    except Exception as e:
        print(f"\n실패: {e}")
        raise SystemExit(1)

    sec = time.perf_counter() - t0
    print(f"\n완료 — 총 {sec:.1f}초 (LLM 소요 {r['latency_ms']/1000:.1f}초)\n")

    print("=" * 56)
    print("단계별 출력 요약")
    print("=" * 56)
    try:
        print(f"  (1) 공략 시간대 : {r['p1'].get('공략_시간대')}")
        menus = r['p2'].get('메뉴안', [])
        print(f"  (2) 메뉴안      : {len(menus)}개")
        for m in menus:
            print(f"        {m.get('안_id')}. {m.get('메뉴명')} "
                  f"— {m.get('페어링_맥주', {}).get('메뉴명')}")
        print(f"  (3) 안별 기획   : {len(r['p3'].get('안별_기획', []))}개")
        ranks = r['final'].get('순위', [])
        print(f"  (4) 순위        : {len(ranks)}개")
        if ranks:
            print(f"        1위: {ranks[0].get('메뉴명')}")
    except Exception as e:
        print(f"  요약 실패: {e}")
        print(json.dumps(r['final'], ensure_ascii=False, indent=2)[:600])
