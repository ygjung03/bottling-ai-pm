"""
바틀링 맥주 라인업 교체 — 판매 종료된 것은 valid_to 를 채우고 새 것을 넣는다

[담당] B
[출처] 2026-09-19 매장 메뉴판 (사용자 확인). 새 맥주의 스타일·도수·맛 특성은
       양조장 공식 페이지와 Untappd 를 다른 LLM 이 찾아 라벨 이미지와 대조한 값이다.
       대표님 확인은 아직이다 — 회신이 오면 이 파일의 값을 고치고 다시 돌린다.

관리 화면의 교체 기능(T10b 나머지)이 아직 없어 스크립트로 한다.
지난 라인업은 지우지 않는다. "8월에는 빅웨이브가 있었다"는 사실이 남아야
그때 만든 기획안을 나중에 재현할 수 있다.

  판매 중        valid_to = NULL
  판매 종료      valid_to = 내린 날짜

실행
  python -m scripts.update_beers            무엇이 바뀔지 보여만 준다
  python -m scripts.update_beers --apply    실제로 반영
"""
import sys
from datetime import date

from db.client import get_client

TODAY = date.today().isoformat()

# 메뉴판 그대로. 빅웨이브가 고정 5종에 있었는데 빠져 고정은 4종이 됐다.
FIXED = {"(논알콜) 체리에이드", "바틀링 라거", "37디그리스라거", "카이저돔 켈러비어"}

# 스타일은 짧게 쓴다. 세트 메뉴명이 "[안주] [맥주 종류] 세트" 라서
# "붕어빵 뉴잉글랜드 IPA 세트" 보다 "붕어빵 IPA 세트" 가 맞다.
# 세부(뉴잉글랜드·호주식)는 맛 특성에 넣어 (2)가 페어링 이유에 쓰게 한다.
#
# 이름                        원/ml  스타일     도수  맛 특성                                       양조장
LINEUP = [
    ("(논알콜) 체리에이드",        8,  "논알콜",   0.0, ["탄산 있음", "체리에이드"],                        None),
    ("바틀링 라거",              12,  "라거",     4.5, ["가벼움", "탄산감 있음"],                          None),
    ("37디그리스라거",           14,  "페일라거",  4.8, ["가벼움", "열대과일향"],                           None),
    ("카이저돔 켈러비어",         16,  "켈러비어",  4.8, ["숙성", "진한 라거"],                              None),
    ("라거 애프터 올",            16,  "라거",     5.0, ["깔끔함", "노블홉향", "상쾌함"],                   "Social DRNKRS × 브루어리304"),
    ("스타우트포터",              16,  "스타우트",  5.0, ["커피향", "구운 몰트향", "진한 풍미"],             "Carlsberg Malaysia (Connor's)"),
    ("산토리 프리미엄 몰츠",       18,  "필스너",   5.5, ["쌉쌀함", "일본식 라거"],                          None),
    ("그레이트 화이트 윗비어",     18,  "윗비어",   4.8, ["시트러스", "고수향", "상쾌함"],                   "Lost Coast Brewery"),
    ("그데이 메잇트",             18,  "페일에일",  4.4, ["열대과일향", "쥬시한 홉향", "산뜻함", "호주식 페일에일"], "Chillhops Brewing Co."),
    ("페일 블루 닷 IPA",          20,  "IPA",     6.3, ["열대과일향", "홉향", "부드러움", "뉴잉글랜드 IPA"],  "서울브루어리"),
    ("갈매기 IPA",               20,  "IPA",     6.5, ["가벼운 IPA", "입문자 추천"],                      None),
    ("트로피칼네스트",            20,  "사워",     6.3, ["망고", "패션프루트", "산미", "과일 사워"],         "플레이그라운드 브루어리 × Eavesdrop"),
]


def rows() -> dict[str, dict]:
    out = {}
    for name, price, style, abv, notes, brewery in LINEUP:
        out[name] = {
            "name": name, "price_per_ml": price, "style": style, "abv": abv,
            "flavor_notes": notes, "brewery": brewery,
            "is_alcohol": abv > 0, "is_fixed": name in FIXED,
            "valid_from": TODAY, "valid_to": None,
        }
    return out


def main() -> None:
    apply = "--apply" in sys.argv
    cli = get_client()
    new = rows()

    cur = (cli.table("beers").select("id,name,price_per_ml,is_fixed")
           .is_("valid_to", "null").execute().data or [])
    cur_by = {r["name"]: r for r in cur}

    retire = [r for r in cur if r["name"] not in new]
    insert = [v for k, v in new.items() if k not in cur_by]
    # 이름은 같은데 단가나 고정 여부가 바뀐 것. 이력이라 갱신하지 않고 종료 + 신규로 넣는다.
    changed = [k for k in new if k in cur_by and (
        float(cur_by[k]["price_per_ml"]) != new[k]["price_per_ml"]
        or bool(cur_by[k]["is_fixed"]) != new[k]["is_fixed"])]

    print(f"판매 중 {len(cur)}종 → {len(new)}종\n")
    print(f"판매 종료 {len(retire)}종 (valid_to = {TODAY})")
    for r in retire:
        print(f"  - {r['name']}")
    print(f"\n신규 {len(insert)}종")
    for v in insert:
        print(f"  + {v['name']:22} {v['price_per_ml']:>3}원/ml  {v['style']:6} {v['abv']}도  "
              f"{', '.join(v['flavor_notes'])}")
    if changed:
        print(f"\n단가·고정 여부가 바뀐 {len(changed)}종 — 종료 후 새로 넣는다")
        for k in changed:
            print(f"  ~ {k}: {cur_by[k]['price_per_ml']}원/{cur_by[k]['is_fixed']} → "
                  f"{new[k]['price_per_ml']}원/{new[k]['is_fixed']}")
    unchanged = [k for k in new if k in cur_by and k not in changed]
    print(f"\n그대로 {len(unchanged)}종: {', '.join(unchanged)}")

    if not apply:
        print("\n--apply 를 붙이면 반영한다.")
        return

    try:
        for r in retire + [cur_by[k] for k in changed]:
            cli.table("beers").update({"valid_to": TODAY}).eq("id", r["id"]).execute()
        to_insert = insert + [new[k] for k in changed]
        if to_insert:
            cli.table("beers").insert(to_insert).execute()
        print(f"\n반영 완료 — 종료 {len(retire) + len(changed)}, 신규 {len(to_insert)}")
    except Exception as e:
        print(f"\n반영 실패: {e}")


if __name__ == "__main__":
    main()
