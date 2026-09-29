"""
갈래별로 AI 에게 넘어가는 「협력사 자원」 쪽지를 확인한다.

폼 갈래가 넷(A / A2 / B / C)이고 단계가 셋(1차 · 3안 도출 · 2차 확정)이라
조합마다 무엇이 실려야 하는지가 다르다. 특히 **협의로 정한 매입가가 실제로
AI 까지 가는지**가 요점이다 — 가지 않으면 2차가 1차와 같은 값을 낸다.

LLM 을 부르지 않는다. 문자열만 만들어 대조하므로 몇 초면 끝난다.

  python -m tests.test_resources
"""
import sys

from chain.inputs import build_partner_resources

# 테스트용 제과점을 본뜬 값. DB 를 읽지 않는다 — 시드 데이터가 바뀌어도
# 이 확인은 같은 것을 재야 한다.
BASE = {
    "name": "테스트용 제과점",
    "category": "제과·디저트",
    "available_slots": "목요일 오전 10시부터 12시 사이에 가능합니다",
    "menu_prices": [
        {"메뉴": "슈크림빵", "가격": 4000, "납품가": 3000},
        {"메뉴": "두바이쫀득 붕어빵", "가격": 3500, "납품가": 3000},
        {"메뉴": "팥붕어빵", "가격": 2000, "납품가": 1000},
    ],
    "menu_prices_review": [],
}

# 폼이 섹션 3 에서 받는 것. A 와 A2 가 둘 다 지나가고, B/C 는 폼 2 에서 받는다.
CONDITIONS = {
    "agreed_price": 2500,
    "supply_qty": "하루 20개, 미리 말씀하시면 30개까지",
    "storage_note": "냉장 보관, 당일 안에",
    "takeout": "가능합니다.",
}

# 폼 섹션 2 에서 받는 것. **A 는 이 섹션을 건너뛴다.**
MENU_FROM_FORM = {"agreed_menu": "슈크림빵", "agreed_sale_price": 4000}


def case(label, partner, *, confirmed=False, agreed_menu=None,
         must_have=(), must_not=()):
    """
    한 갈래를 만들어 보고 들어가야 할 말과 들어가면 안 될 말을 본다.

    무엇이 들어갔는지만 보지 않고 **들어가면 안 되는 것도 본다.** 협의 전인데
    확정값이 새거나, 메뉴가 정해졌는데 다른 메뉴가 남아 있는 것이 그것이다.
    """
    text = build_partner_resources(partner, confirmed=confirmed,
                                   agreed_menu=agreed_menu)
    bad = [s for s in must_have if s not in text]
    leak = [s for s in must_not if s in text]

    ok = not bad and not leak
    print(f"  {'OK ' if ok else 'X  '}{label}")
    for s in bad:
        print(f"        빠짐   {s}")
    for s in leak:
        print(f"        샘     {s}")
    if not ok:
        print("      ── 만들어진 쪽지 ──")
        for line in text.splitlines():
            print(f"      {line[:130]}")
    return ok


def main() -> None:
    a_form = {**BASE, **CONDITIONS, "reply_choice": "A"}          # 섹션 2 건너뜀
    a2_form = {**BASE, **CONDITIONS, **MENU_FROM_FORM, "reply_choice": "A2"}
    bc_photo = {**BASE, "reply_choice": "B"}                      # 폼 1 만 냈다
    bc_done = {**BASE, **CONDITIONS, **MENU_FROM_FORM, "reply_choice": "B"}

    print("1차 — 협의 전이다. 확정값이 새면 안 된다")
    results = [
        case("폼을 안 낸 협력사", BASE,
             must_have=["슈크림빵 판매가 4,000원 납품가 3,000원", "팥붕어빵"],
             must_not=["[확정]", "확정된 협업 메뉴"]),
        case("폼은 냈지만 1차를 다시 만든다 (시드)", a2_form,
             must_have=["팥붕어빵"],
             must_not=["[확정]", "확정된 협업 메뉴", "2,500원"]),
    ]

    print()
    print("3안 도출 — A2 는 메뉴가 정해졌고, B/C 는 아직이다")
    results += [
        case("A2 — 메뉴 고정. 그 메뉴만 실린다", a2_form, confirmed=True,
             must_have=["확정된 협업 메뉴", "메뉴: 슈크림빵",
                        "납품가 2,500원 [확정]", "하루 20개"],
             must_not=["팥붕어빵", "두바이쫀득"]),
        case("B/C — 사진만 받았다. 전체 목록이 실린다", bc_photo,
             must_have=["슈크림빵", "팥붕어빵", "두바이쫀득"],
             must_not=["[확정]", "확정된 협업 메뉴"]),
    ]

    print()
    print("2차 확정 — 협의로 정한 매입가가 반드시 실려야 한다")
    results += [
        case("A — 폼에 메뉴가 없어 1차 안에서 받는다", a_form, confirmed=True,
             agreed_menu="팥붕어빵 3개",
             must_have=["메뉴: 팥붕어빵 3개", "납품가 2,500원 [확정]",
                        "판매가 미입력", "냉장 보관"],
             must_not=["슈크림빵", "두바이쫀득"]),
        case("A2 — 폼의 메뉴를 쓴다", a2_form, confirmed=True,
             must_have=["메뉴: 슈크림빵", "납품가 2,500원 [확정]", "판매가 4,000원"],
             must_not=["팥붕어빵"]),
        case("B/C — 폼 2 의 메뉴를 쓴다", bc_done, confirmed=True,
             must_have=["메뉴: 슈크림빵", "납품가 2,500원 [확정]"],
             must_not=["팥붕어빵"]),
    ]

    print()
    print("어긋나는 경우 — 조용히 넘어가면 안 된다")
    results += [
        case("폼을 다시 내 메뉴가 바뀌었다. 폼 값이 이긴다",
             {**a2_form, "agreed_menu": "두바이쫀득 붕어빵"}, confirmed=True,
             agreed_menu="슈크림빵",              # 화면이 들고 있던 옛 메뉴
             must_have=["메뉴: 두바이쫀득 붕어빵"],
             must_not=["메뉴: 슈크림빵"]),
        case("confirmed 인데 메뉴를 모른다 (호출 실수)", bc_photo, confirmed=True,
             must_have=["확정 메뉴가 넘어오지 않았다", "팥붕어빵"],
             must_not=["[확정]"]),
    ]

    print()
    print("-" * 60)
    bad = results.count(False)
    print(f"  {len(results)}건 중 {bad}건 어긋남" if bad
          else f"  {len(results)}건 모두 통과")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()