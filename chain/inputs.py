"""
체인 입력 조립 — DB 값을 프롬프트에 넣을 문장으로 변환

[담당] B
[티켓] T12

runner.run() 이 받는 입력을 만드는 곳이다.
컨텍스트 빌더(context/builder.py)가 상권 데이터를 맡고,
여기는 바틀링·협력사 자원처럼 우리가 직접 관리하는 값을 맡는다.

대부분은 문자열이다. 제약만 단계별로 갈려 dict 를 돌려준다
(build_constraints, 명세서 1-5 의 target 필드).

[원칙]
  - 없는 값을 지어내지 않는다. 비면 "데이터 없음"으로 적는다
  - 판단하지 않는다. 어느 맥주가 어울리는지는 LLM 이 정한다
  - 단위를 명시한다. 20 이 원인지 ml 인지 프롬프트만 보고 알 수 있어야 한다
"""
from __future__ import annotations

from datetime import date, timedelta

from chain.loader import load
from db.client import get_client

NO_DATA = "데이터 없음"

# ══════════════════════════════════════════
# 바틀링 고유 정보 — 테이블이 없어 상수로 둔다
# ══════════════════════════════════════════

# 바틀링 주방·공간·장비 여건
#
# [출처] 자료요청서 A-2·A-3 (2026-08-21 대표님 회신)
#        매장 수용 7인, 테이크아웃 중심 — 1차 현장방문 관찰 (8/17)
#
# [2026-09-08] 협업 기획에서 빠졌다.
#   8/31 2차 방문으로 협업 형태가 「완제품 매입 후 판매」 하나로 좁혀졌다
#   (기획서 6-1). 협력사가 자기 장비로 만들어 오므로 바틀링 주방 여건이
#   개입하지 않는다. (2) 셰프에 더 이상 넘기지 않는다.
#
#   지우지 않고 남기는 것은 「가게 자체 메뉴 개발」(기획서 3-5 ⑦)이
#   이 값을 쓰기 때문이다. 그 기능은 (2)의 변형으로 만들며, 협력사 자원
#   대신 주방 여건이 핵심 제약이 된다. 지금은 어디서도 참조하지 않는다.
#
#   완제품이라도 매장 보관은 필요하다. 냉장·냉동 용량만 p2_chef.yaml
#   본문에 상수로 적어 두었다 (명세서 1-2).
#
# 처음에 우리가 "전자레인지·에어프라이어만, 화기 불가"로 짐작했으나
# 실제로는 가스·전기 모두 쓸 수 있고 조리기구도 갖춰져 있다.
# 짐작으로 제약을 좁히면 만들 수 있는 메뉴를 스스로 지운다.
#
# 넣어야 하는 것이 둘이다.
#
#   화구 1개    — 화기가 되더라도 하나뿐이라 동시 조리가 안 된다
#   냉장·냉동   — "미리 전처리해두면 괜찮다"의 실현 조건이다.
#                보관 공간이 있어야 4분 제한을 우회할 수 있다
#
# A-3 장비 표의 붕어빵기계는 협력사에게서 빌려오는 것이라
# 여기가 아니라 partners.equipment 에 둔다.


# 바틀링이 이미 갖고 있는 식재료.
#
# 협업이 완제품 매입 하나가 되면서(기획서 6-1) 협력사가 무엇으로 만드는지는
# 알 필요가 없어졌다. 사 오는 것은 완성품이고, 변형은 바틀링 쪽에서 한다.
# 그래서 (2)가 알아야 하는 것은 바틀링이 무엇을 갖고 있느냐다 —
# 이미 있는 재료로 진행할 수 있으면 새 재료를 사 올 필요가 없다.
#
# [미확보] 대표님께 여쭤야 한다 (자료요청 목록). 짐작으로 채우면 없는 재료를
# 전제한 메뉴가 나온다. 비어 있는 동안 (2)는 더하는 것을 전부 「사 온다」로
# 적고 바틀링_준비에 올린다.
BOTTLING_INGREDIENTS = NO_DATA

KITCHEN = """[조리 여건]
- 조리 시간: 주문 접수부터 포장까지 4분 이내.
  단, 미리 전처리해두고 바로 낼 수 있으면 시간 제한을 넘겨도 된다
- 화기: 가스·전기 모두 사용 가능. 단 화구는 1개뿐이라 동시 조리 불가
- 보유 조리기구: 생맥주 셀프탭 12개, 생맥주 디스펜서 1개,
  전기화덕피자오븐, 전자레인지, 화구 1개, 어묵중탕기 1개,
  오렌지쥬스 착즙기 1개, 그릴 1개
- 냉장·냉동: 1.5평 워크인냉장고, 25박스 냉동칸, 음료냉장고 1개

[공간]
- 매장 수용: 7인 내외, 테이크아웃 중심
- 외부 공간: 4인 테이블 3개 사용 가능
- 외부 전기 콘센트 없음 (외부 공간에서 전기 장비 사용 불가)

[장비 이동]
- 화덕피자오븐 / 어묵중탕기 / 생맥주 셀프탭 / 생맥주 디스펜서는
  자차로 옮길 수 있다 (협력사 매장으로 가서 진행할 수도 있다)"""

# 마진 기준값 — (2) 셰프 입력.
#
# [출처] 8/31 2차 방문 대표님 청취 (기획서 3-5 ①)
#
# 판매가를 정할 때 쓴다. 지금까지 (2)가 원가를 "산출 불가"로 두면
# 판매가까지 0 으로 두는 일이 있었는데, 그러면 (4)가 평가할 수 없다.
# 실제 마진율을 주어 원가를 몰라도 판매가를 정할 근거를 만든다.
#
# 세 건뿐이라 근거가 얇다. 이것으로 충분한지는 U18 로 남아 있다.
MARGIN_REF = """- 감자튀김: 마진율 70%
- 닭다리: 마진율 50～60%
- 화덕피자 도우: 원가 500원 — 도우를 많이 쓰는 형태면 마진이 남는다

※ 이 값은 바틀링이 직접 만드는 경우의 기준이다.
   완제품 매입에서는 매입가가 곧 원가이므로 판매가를 정할 때 참고로만 쓴다."""


# 날씨별 선호 — (2) 셰프 입력.
#
# [출처] 8/31 2차 방문 대표님 청취 (기획서 5장)
#
# 데이터가 말하지 않는 것을 사람이 안다. 상권 데이터로는 어느 맥주가
# 어느 날씨에 나가는지 알 수 없다. 대표님이 실제로 관찰한 것이다.
WEATHER_PREF = """- 비 오거나 추운 날: 흑맥주 (캄캄)
- 더운 날: 라거 — 시원한 것

※ 컨텍스트의 날씨는 대상 시점의 예보가 아니라 최근 관측치다 (U12).
   페어링 판단의 참고로만 쓴다."""


# 기존 협업 3건의 결과 — (3) 마케터 입력.
#
# [출처] 8/31 2차 방문 대표님 청취 (기획서 3-4)
#
# 시스템 도입 전에 대표님이 직접 하셨던 협업이다. 세 건 모두 홍보에서
# 아쉬웠고, 그래서 (3)이 이 프로젝트의 실제 병목이다.
#
# 사례를 그대로 흉내내게 하지 않는다. 규칙(constraints C001～C003)이
# 이미 이것을 긍정형으로 담고 있으므로, 여기서는 왜 그 규칙이 있는지를
# 이해하는 맥락으로만 쓰인다 (명세서 1-3).
#
# [2026-09-08] 상호를 업종으로 바꿨다. 이유는 둘인데 조치는 하나로 겹친다.
#   저장소가 공개라 상대 업체의 실명에 "협업이 실패했다"가 붙어 있었다.
#   그리고 명세서 D1 이 경계하는 표면 모방 — 상호 자체가 메뉴를 연상시켜
#   계속 같은 계열을 제안하게 만든다.
#   홍보가 왜 실패했는지가 정보이고 어느 가게였는지는 정보가 아니다.
#   어느 건이 어느 가게인지는 docs/private/상호_대응표.md 에 있다.
PAST_CASES = """- 제과·디저트 협업 (2025, 대형 행사 기간): 유동인구는 많았으나
  유인 요인이 부족했다. 현수막만으로는 부족했다
- 화덕 요리 협업 (2025): 반응은 괜찮았으나 맛이 대중적이지 않았다
- 카페 협업 (2025): 파는지도 모를 정도로 인지가 부족했다.
  소요 대비 효과가 없어 중단했다

※ 세 건 모두 홍보에서 아쉬웠다. 대표님 말씀은
   "길게 꾸준히 하든가, 하기 전에 사람들이 많이 인지할 수 있게 콘텐츠를 뽑든가"였다."""


# 유행 메뉴 — (2) 셰프 입력.
#
# 메뉴 검색 경로(명세서 3-5)로 시작한 경우에만 대표님이 입력한 메뉴명이
# 넘어온다. 그 경로가 아니면 이 값이다. "없음"이 아니라 "데이터 없음"인
# 것은, 축으로 삼을 메뉴가 없다는 뜻이지 메뉴를 자유롭게 정하라는 뜻이
# 아님을 구분하기 위해서다.
NO_TREND_MENU = f"{NO_DATA} (메뉴 검색 경로로 시작하지 않음)"


# 바틀링 SNS 자산 — (3) 마케터 입력.
#
# 아직 받지 못했다. 자료요청서 A-4 는 협력사 SNS 만 물었고
# 바틀링 자신의 계정 정보는 항목에 없었다.
# 8/31 2차 방문에서 계정명과 주 콘텐츠 형식을 받는다.
#
# 그럴듯한 값을 지어넣지 않는다. 없는 계정을 있다고 해 두면 (3)이
# 그 채널로 홍보를 짜고, (4)가 그것을 검수한다.
# 없는 근거 위에 결론이 쌓인다.
BOTTLING_SNS = f"{NO_DATA} (8/31 방문에서 확인 예정)"


# 추천 사유 — (4) 컨설턴트 입력.
#
# T15 추천 엔진(W2)이 만드는 값이다. 아직 없다.
# 대표님이 협력사를 직접 고른 경우에도 이 값은 비므로,
# 미착수 상태와 직접 지정을 구분해 적는다.
NO_REC_REASON = f"{NO_DATA} (추천 엔진 미구현 — 협력사를 직접 지정함)"


# 협력사 시드 데이터 — T21 협력사 입력 폼 전까지 쓰는 가상 값.
#
# 실제 협력사는 확정되었으나 판매 메뉴와 가격은 협력사가 폼에 직접
# 입력할 내용이라 아직 없다. 형식만 같게 지어낸 값이다.
#
# 상수로 두지 않고 partners 테이블에 넣는다. 폼이 붙는 순간
# 조회 경로가 그대로 쓰이도록, 지금부터 DB 를 거쳐 읽는다.
#
# [2026-09-08] 실존 상호를 업종 표기로 바꿨다. 지어낸 단가·불가조건이
#   실존 상호에 붙어 있어, 파일만 보면 그 가게의 실제 납품 조건으로 읽혔다.
#   가상 상호를 새로 지으면 그것도 실제 가게처럼 읽히므로 업종을 그대로 쓴다.
#   invite_code 도 뺐다 — 코드가 곧 신원인데(app/auth.py) 공개 저장소에
#   적힌 값은 이미 코드가 아니다. seed_partner.py 가 무작위로 발급한다.
SEED_PARTNER = {
    "name": "테스트용 제과점",
    "category": "제과·디저트",
    "signature_menu": "붕어빵",
    # 협력사가 지금 팔고 있는 것과 그 가격. 협업이 완제품 매입 하나이므로
    # 새 메뉴를 만드는 것이 아니라 팔던 것을 변형한다 (기획서 6-1).
    # 납품가는 메뉴마다 받는다. 단가 하나로는 메뉴별 차이를 덮을 수 없다.
    "menu_prices": [
        {"메뉴": "붕어빵 3개", "가격": 3000, "납품가": 2100},
        {"메뉴": "슈크림 붕어빵 3개", "가격": 3500, "납품가": 2500},
        {"메뉴": "미니 붕어빵 10개", "가격": 5000, "납품가": 3500},
    ],
    "available_slots": "화~일 오전 중 가능. 월요일 휴무",
    # 체인에는 안 들어간다. 대표님이 연락하실 때 보는 값이다.
    "contact_slots": "평일 오전",
    "sns_channel": "인스타그램",
    "sns_content_type": "릴스",
    # 완제품 매입으로 좁혀지면서 성격이 바뀌었다. 출장·장비 대여는 이제
    # 없는 개념이고, 주말 얘기는 납품 가능 요일 쪽이 받는다.
    "blockers": ["반죽은 당일 소진해야 하므로 전날 만들어 둘 수 없다",
                 "한 번에 50개까지만 만들 수 있다",
                 "받아서 다시 데우면 맛이 변하므로 그대로 내야 한다"],
}


# ══════════════════════════════════════════
# 조립
# ══════════════════════════════════════════

def _num(v) -> str:
    """
    소수점이 무의미하면 떼어낸다.

    NUMERIC(5,1) 컬럼이라 8 원이 8.0 으로 돌아온다. 단가는 전부 정수인데
    소수점이 붙으면 프롬프트에서 다른 값처럼 읽힐 여지가 있다.
    도수는 4.5 처럼 소수가 실제 값이므로 그때는 남긴다.
    """
    f = float(v)
    return str(int(f)) if f == int(f) else str(f)


def build_beer_list() -> str:
    """
    판매 중인 맥주 라인업.

    valid_to 가 NULL 인 것만 고른다. 월 1회 3종을 교체하므로
    지난 라인업이 섞이면 지금 팔지 않는 맥주로 페어링이 나온다.

    저가 순으로 적는다. 단가는 세트 값(맥주 500ml)을 계산할 때 쓴다.
    9/19 부터 단가는 페어링을 고르는 기준이 아니다 — 고가 맥주가
    고마진이 아닐 수 있어 맛의 적절성으로만 본다. 정렬은 읽기 편하라고 남겼다.

    고정 여부를 표기한다. 기획안을 만들고 실행하기까지 며칠이 걸리는데
    그 사이 교체분은 사라질 수 있다. 실증 구간(9/21～10/16) 안에도
    최소 한 번은 교체된다. 어느 것이 남아 있을 맥주인지 알아야
    실행 시점에 없는 맥주로 기획하는 일을 피한다.

    논알콜을 목록에서 빼지 않는다. 페어링에서 제외하는 것은
    프롬프트의 지시이지 데이터의 성질이 아니다. 여기서 지우면
    "논알콜은 제외한다"는 지시가 무엇을 가리키는지 알 수 없어진다.
    """
    try:
        rows = (get_client().table("beers")
                .select("*").is_("valid_to", "null")
                .order("price_per_ml").execute().data or [])
    except Exception as e:
        return f"{NO_DATA} (조회 실패: {e})"

    if not rows:
        return f"{NO_DATA} (적재 전)"

    lines = []
    for r in rows:
        parts = [str(r["name"]), f"{_num(r['price_per_ml'])}원/ml"]

        # 스타일·도수·맛이 비면 "데이터 없음"으로 적는다. 말없이 빼면 LLM 이
        # 이름만 보고 지어낸다 (원칙 ③). 새 맥주를 단가만 알고 넣을 때 그렇다.
        style = r.get("style")
        parts.append(str(style) if style else "스타일 데이터 없음")

        # 도수 0 은 "논알콜"로 적는다. 다만 스타일이 이미 '논알콜'이면
        # 같은 말이 두 번 나오므로 생략한다.
        abv = r.get("abv")
        if abv is None:
            parts.append("도수 데이터 없음")
        elif float(abv) > 0:
            parts.append(f"{_num(abv)}도")
        elif style != "논알콜":
            parts.append("논알콜")

        notes = r.get("flavor_notes") or []
        parts.append(", ".join(notes) if notes else "맛 특성 데이터 없음")

        mark = "[고정]" if r.get("is_fixed") else "[교체 가능]"
        lines.append("- " + " / ".join(parts) + f" {mark}")

    return "\n".join(lines)


def fetch_partner(partner_id: int | None = None) -> dict | None:
    """
    협력사 1곳. id 를 주지 않으면 가장 먼저 등록된 곳을 쓴다.

    T21 에서 협력사가 폼에 입력하면 partners 에 행이 쌓인다.
    지금은 시드 1건뿐이라 id 없이 불러도 그 행이 나온다.
    """
    try:
        q = get_client().table("partners").select("*")
        if partner_id is not None:
            q = q.eq("id", partner_id)
        rows = q.order("id").limit(1).execute().data or []
    except Exception:
        return None
    return rows[0] if rows else None


def _menus(partner: dict) -> str:
    """
    협력사가 지금 팔고 있는 메뉴와 두 가지 값.

    협업이 완제품 매입 하나이므로(기획서 6-1) 셰프가 할 일은 새 메뉴를
    만드는 것이 아니라 팔던 것을 고르는 것이다.

    판매가는 손님에게 받는 값이고 납품가는 바틀링에 주는 값이다.
    납품가를 메뉴마다 받는 이유는 메뉴에 따라 값이 다르기 때문이다.
    단가 하나로 모든 메뉴를 덮으면 어떤 메뉴는 소매가보다 비싸게 매입하는
    값이 나온다.

    납품가는 선택 입력이라 비어 있을 수 있다. 그때는 협의로 정한다.

    1차 기획안은 협력사가 입력하기 전에 블로그 후기에서 본 값으로 만든다.
    그 값에는 「후기 5건, 2026-08」 같은 근거가 붙는다. 판매가 뒤에 그대로
    실어 (2)가 얼마나 믿을 값인지 가늠하게 한다 — 상권 데이터에 관측
    건수를 붙이는 것과 같다.
    """
    parts = []
    for r in partner.get("menu_prices") or []:
        name = str(r.get("메뉴") or "").strip()
        if not name:
            continue
        price, wholesale = r.get("가격"), r.get("납품가")
        basis = str(r.get("근거") or "").strip()
        bits = [name]
        if price:
            bits.append(f"판매가 {int(price):,}원"
                        + (f" ({basis})" if basis else ""))
        else:
            bits.append("판매가 미입력")
        bits.append(f"납품가 {int(wholesale):,}원" if wholesale
                    else "납품가 미정 (협의 대상)")
        parts.append(" ".join(bits))
    return " / ".join(parts) if parts else NO_DATA


def build_partner_resources(partner: dict | None) -> str:
    """
    협력사가 가진 것. 셰프가 메뉴를 짜는 재료다.

    빈 항목은 줄째로 빼지 않고 "데이터 없음"으로 적는다.
    줄이 없으면 협력사가 안 가진 것인지 아직 입력하지 않은 것인지
    구분되지 않아, 없는 것을 전제한 메뉴가 나온다.

    협력사의 보유 식재료와 장비는 싣지 않는다. 완제품을 사 오므로
    무엇으로 어떻게 만드는지는 알 필요가 없다. 바틀링이 쓸 수 있는
    기구는 p2_chef.yaml 의 [바틀링 매장 여건] 에 적혀 있다.

    납품가는 메뉴마다 다르므로 「판매 중인 메뉴」 줄 안에 함께 싣는다.
    매장 전체에 하나의 단가를 두면 어떤 메뉴에서는 소매가보다 비싸게
    매입하는 값이 나온다.

    (4)에도 이 문자열을 넘긴다. 역할분담을 쓰려면 상대가 무엇을 가졌는지
    알아야 한다(명세서 1-4).
    """
    if partner is None:
        return f"{NO_DATA} (협력사 미선택)"

    head = f"{partner.get('name', '?')} / {partner.get('category') or NO_DATA}"
    return "\n".join([
        head,
        f"- 대표 메뉴: {partner.get('signature_menu') or NO_DATA}",
        f"- 판매 중인 메뉴: {_menus(partner)}",
        f"- 납품 가능 요일·시간: {partner.get('available_slots') or NO_DATA}",
    ])


# 제약을 받는 단계. (1) 상권분석가는 받지 않는다 — 데이터를 읽을 뿐
# 기획을 만들지 않으므로 지킬 제약이 없다.
CONSTRAINT_STEPS = ("p2", "p3", "p4")


def build_constraints() -> dict[str, str]:
    """
    단계별 하드 제약. constraints.yaml 의 target 으로 갈라 담는다.

    규칙이 7건으로 늘면서 (2) 셰프와 (3) 마케터에 해당하는 것이 갈렸다
    (명세서 1-5). 모든 규칙을 모든 단계에 넣으면 프롬프트가 길어지고,
    관계없는 제약이 판단을 흐린다. target 이 없는 규칙은 전 단계에 넣는다.

    [(4)만 전부 받는다] (4)는 세 안을 최종 검수하는 단계다. 검수 2번이
    준비 기간 3일(C007, target=p2)을 명시적으로 참조하므로, (2)(3)의
    제약을 모르면 위반을 잡을 수 없다. 검수자가 규칙을 못 보는 구조는
    성립하지 않는다.

    origin 은 넣지 않는다. 이력 추적용이며 프롬프트에는 rule 만 간다.
    """
    try:
        rules = load("constraints").get("constraints") or []
    except Exception as e:
        return {s: f"{NO_DATA} (constraints.yaml 조회 실패: {e})"
                for s in CONSTRAINT_STEPS}

    out = {}
    for step in CONSTRAINT_STEPS:
        picked = (rules if step == "p4"
                  else [r for r in rules if r.get("target") in (None, step)])
        out[step] = ("\n".join(f"- {r['rule']}" for r in picked) if picked
                     else f"{NO_DATA} (해당 단계에 적용할 규칙 없음)")
    return out


# 협력사가 「지켜야 할 조건이 없다」고 답한 것으로 읽히는 표현.
# 폼에서 필수로 받으면서 없을 때는 「없음」이라고 적게 안내하는데,
# 그것을 그대로 넘기면 "없음"을 지켜야 하는 조건으로 읽는다.
NO_BLOCKER = {"없음", "없습니다", "없어요", "해당 없음", "특별히 없음",
              "특별히 없습니다", "-", "무"}


def build_partner_blockers(partner: dict | None) -> str:
    """
    협력사가 지켜 달라고 한 조건. 지키지 못하는 안은 폐기된다(명세서 1-2).

    세 상태를 구분한다.

      비어 있음    아직 폼을 내지 않은 협력사다. 협력사 행을 먼저 만들고
                  코드를 보내므로 첫 제출까지는 이 상태다.
                  조건이 없는 것으로 단정하면 안 된다
      「없음」     협력사가 조건이 없다고 확인해 준 것이다
      실제 조건    목록으로 넘긴다
    """
    if partner is None:
        return f"{NO_DATA} (협력사 미선택)"

    items = [str(x).strip() for x in (partner.get("blockers") or [])]
    items = [x for x in items if x]
    if not items:
        return f"{NO_DATA} (협력사가 아직 입력하지 않음)"

    real = [x for x in items if x not in NO_BLOCKER]
    if not real:
        return "지켜야 할 조건 없음 (협력사가 확인해 준 사실)"
    return "\n".join(f"- {x}" for x in real)


def build_events(target: date, days: int = 30) -> str:
    """
    대상 시점 이후 N일 내 행사. (3) 마케터가 연계 여부를 판단한다.

    A 담당 T10 이 적재 전이라 지금은 비어 있다.
    citydata 의 CULTURALEVENTINFO 로 대체할 수 있는지 확인했으나
    두 지점 모두 0건이었다. 8/29 광진 뮤직 페스타도 잡히지 않아
    구청 주최 행사는 서울시 API 에서 누락되는 것으로 보인다.
    """
    try:
        rows = (get_client().table("events").select("*")
                .gte("end_date", target.isoformat())
                .lte("start_date", (target + timedelta(days=days)).isoformat())
                .order("start_date").limit(5).execute().data or [])
    except Exception:
        return f"{NO_DATA} (적재 전)"

    if not rows:
        return f"{NO_DATA} (적재 전)"

    lines = []
    for e in rows:
        dist = f", 약 {e['distance_m']}m" if e.get("distance_m") else ""
        lines.append(f"- {e.get('title')} / {e.get('start_date')}～"
                     f"{e.get('end_date')} / {e.get('place')}{dist}")
    return "\n".join(lines)


def build_partner_sns(partner: dict | None) -> str:
    """
    (3) 마케터 입력. 협력사에 무엇을 올려달라고 요청할지 정하는 근거다.

    알아야 하는 것은 둘이다 — 어디에 올리는 것인지, 무엇을 올려달라고
    요청할 수 있는지.

    「SNS 없음」과 「미입력」을 구분한다. 없다고 확인된 것이면 (3)이
    협력사에 홍보를 요청하지 않고 바틀링이 할 수 있는 것만으로 짠다.
    아직 안 적은 것이면 계정이 있는지조차 모르므로 그 판단을 미뤄야 한다.
    """
    if partner is None:
        return f"{NO_DATA} (협력사 미선택)"

    ch = partner.get("sns_channel")
    if not ch:
        return f"{NO_DATA} (협력사 미입력)"
    if ch == "안 합니다":
        return "운영하는 SNS 없음 (협력사가 확인해 준 사실)"
    return f"{ch} / 주 콘텐츠 {partner.get('sns_content_type') or NO_DATA}"


if __name__ == "__main__":
    from datetime import datetime, timezone

    print("[바틀링 맥주 라인업]")
    print(build_beer_list())
    print()
    print("[마진 기준값]")
    print(MARGIN_REF)
    print()
    print("[날씨별 선호]")
    print(WEATHER_PREF)
    print()
    print("[기존 협업 사례]")
    print(PAST_CASES)
    print()
    print("[바틀링 SNS]")
    print(BOTTLING_SNS)

    print()
    print("[단계별 제약]")
    for step, text in build_constraints().items():
        print(f"  ({step})")
        for line in text.splitlines():
            print(f"    {line}")

    p = fetch_partner()
    print()
    print("[협력사 보유 자원]")
    print(build_partner_resources(p))
    print()
    print("[협력사 불가 조건]")
    print(build_partner_blockers(p))
    print()
    print("[협력사 SNS]")
    print(build_partner_sns(p))
    print()
    print("[인근 행사 (30일 내)]")
    today = datetime.now(timezone(timedelta(hours=9))).date()
    print(build_events(today))
