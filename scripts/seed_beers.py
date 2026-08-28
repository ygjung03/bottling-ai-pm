"""
바틀링 맥주 라인업 최초 적재 — T10b

[담당] B
[출처] 자료요청서 A-1 (2026-08-21 대표님 회신) + 네이버 지도 단가

월 1회 3종을 교체하므로 이력을 남긴다. 지금 파는 것만 덮어쓰면
"8월에는 사워가 있었다" 같은 사실이 사라져, 지난 협업 기획을
나중에 재현할 수 없다.

  판매 중        valid_to = NULL
  판매 종료      valid_to = 내린 날짜

교체 시에는 이 파일을 고치지 말고 관리 화면에서 처리한다.
여기는 최초 1회 적재용이다.

실행: python -m scripts.seed_beers
"""
from db.client import get_client

VALID_FROM = "2026-08-21"   # 자료요청서 회신일

# 대표님이 자료요청서 A-1 에서 굵게 표시하신 고정 메뉴.
# 나머지는 월 1회 3종씩 교체된다. 셀프탭 12개 중 고정 5 + 교체 7 구조다.
FIXED = {"(논알콜) 체리에이드", "바틀링 라거", "37디그리스라거",
         "카이저돔 켈러비어", "빅웨이브"}

# 스타일·도수·맛 특성은 대표님 회신 그대로다.
# 우리가 짐작해 적어둔 것을 대표님이 고쳐주신 결과이므로
# 임의로 다듬지 않는다. 페어링 판단의 유일한 근거다.
#
# 흔들흔들(사워, 6도)은 8/28 확인 시점에 판매 목록에서 빠져 있어
# 제외했다. 단가를 알 수 없어 추정으로 채우지 않는다.
BEERS = [
    # 이름                   원/ml  스타일       도수   맛 특성
    ("(논알콜) 체리에이드",     8,  "논알콜",     0.0, ["탄산 있음", "체리에이드"]),
    ("바틀링 라거",           12,  "라거",       4.5, ["가벼움", "탄산감 있음"]),
    ("37디그리스라거",        14,  "페일라거",    4.8, ["가벼움", "열대과일향"]),
    ("카이저돔 켈러비어",      16,  "켈러비어",    4.8, ["숙성", "진한 라거"]),
    ("맘마미아",              16,  "라거",       4.8, ["화덕피자와 어울림"]),
    ("캄캄",                 16,  "포터",       5.0, ["커피향", "초콜릿향"]),
    ("산토리 프리미엄 몰츠",   18,  "필스너",     5.5, ["쌉쌀함", "일본식 라거"]),
    ("워터멜론 위트에일",      20,  "위트에일",    5.0, ["수박향", "밀맥주"]),
    ("갈매기 IPA",           20,  "IPA",       6.5, ["가벼운 IPA", "입문자 추천"]),
    ("끽비어 삐약 ver2",      20,  "IPA",       6.5, ["쌉쌀함", "쥬시한 홉향"]),
    ("빅웨이브",              20,  "골든에일",    4.8, ["열대과일향"]),
]

# 대표님이 "골든에일?"로 물음표를 붙여 회신하셨다.
# 8/31 방문에서 확인한다.
UNCERTAIN = {"빅웨이브": "스타일 미확정 (대표님도 확신 없음)"}


def rows() -> list[dict]:
    out = []
    for name, price, style, abv, notes in BEERS:
        out.append({
            "name": name,
            "price_per_ml": price,
            "style": style,
            "abv": abv,
            "flavor_notes": notes,
            "is_alcohol": abv > 0,
            "is_fixed": name in FIXED,
            "valid_from": VALID_FROM,
            "valid_to": None,
        })
    return out


def main() -> None:
    data = rows()

    print(f"적재 대상 {len(data)}종 (고정 {sum(r['is_fixed'] for r in data)}종)\n")
    print(f"  {'맥주':22} {'원/ml':>6} {'스타일':10} {'도수':>5} {'구분':>6}  맛 특성")
    for r in data:
        mark = "  ★" if r["name"] in UNCERTAIN else ""
        kind = "고정" if r["is_fixed"] else "교체"
        print(f"  {r['name']:22} {r['price_per_ml']:>6} "
              f"{r['style']:10} {r['abv']:>5} {kind:>6}  "
              f"{', '.join(r['flavor_notes'])}{mark}")

    for name, why in UNCERTAIN.items():
        print(f"\n  ★ {name}: {why}")

    cli = get_client()

    # 이미 들어 있으면 중복 적재를 막는다.
    # UNIQUE 제약이 없는 테이블이라 upsert 로 걸러지지 않는다.
    try:
        cur = (cli.table("beers").select("name")
               .is_("valid_to", "null").execute().data or [])
    except Exception as e:
        print(f"\n조회 실패: {e}")
        return

    if cur:
        print(f"\n이미 판매 중으로 등록된 {len(cur)}종이 있다:")
        for r in cur:
            print(f"  - {r['name']}")
        print("\n중복 적재를 막기 위해 중단한다.")
        print("다시 넣으려면 기존 행을 지우거나 valid_to 를 채운 뒤 실행할 것.")
        return

    try:
        cli.table("beers").insert(data).execute()
        print(f"\n적재 완료 {len(data)}종")
    except Exception as e:
        print(f"\n적재 실패: {e}")


if __name__ == "__main__":
    main()
