"""
협력사 시드 적재 — T12 검증용

[담당] B

T21 협력사 입력 폼이 붙기 전까지 (2) 셰프를 테스트할 데이터가 없다.
상수로 두지 않고 partners 테이블에 넣는 이유는, 폼이 붙는 순간
조회 경로가 그대로 쓰이도록 지금부터 DB 를 거쳐 읽기 위해서다.

값은 가상이다. 실제 협력사는 확정되었으나(자료요청서 A-4)
보유 식재료·장비는 협력사가 직접 입력할 내용이라 아직 없다.

실행: python -m scripts.seed_partner
"""
from chain.inputs import SEED_PARTNER
from db.client import get_client


def main() -> None:
    cli = get_client()
    code = SEED_PARTNER["invite_code"]

    print(f"적재 대상: {SEED_PARTNER['name']} ({SEED_PARTNER['category']})")
    for k, v in SEED_PARTNER.items():
        shown = ", ".join(map(str, v)) if isinstance(v, list) else v
        print(f"  {k:18} {shown}")

    try:
        cur = (cli.table("partners").select("id, name")
               .eq("invite_code", code).execute().data or [])
    except Exception as e:
        print(f"\n조회 실패: {e}")
        return

    if cur:
        print(f"\n이미 등록되어 있다 (id={cur[0]['id']}, {cur[0]['name']}).")
        print("중복 적재를 막기 위해 중단한다.")
        return

    try:
        cli.table("partners").insert(SEED_PARTNER).execute()
        print("\n적재 완료 1건")
    except Exception as e:
        print(f"\n적재 실패: {e}")


if __name__ == "__main__":
    main()
