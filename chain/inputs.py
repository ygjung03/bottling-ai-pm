"""
체인 입력 조립 — DB 값을 프롬프트에 넣을 문장으로 변환

[담당] B
[티켓] T12

runner.run() 은 모든 입력을 문자열로 받는다. 그 문자열을 만드는 곳이다.
컨텍스트 빌더(context/builder.py)가 상권 데이터를 맡고,
여기는 바틀링·협력사 자원처럼 우리가 직접 관리하는 값을 맡는다.

[원칙]
  - 없는 값을 지어내지 않는다. 비면 "데이터 없음"으로 적는다
  - 판단하지 않는다. 어느 맥주가 어울리는지는 LLM 이 정한다
  - 단위를 명시한다. 20 이 원인지 ml 인지 프롬프트만 보고 알 수 있어야 한다
"""
from __future__ import annotations

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
# 처음에 우리가 "전자레인지·에어프라이어만, 화기 불가"로 짐작했으나
# 실제로는 가스·전기 모두 쓸 수 있고 조리기구도 갖춰져 있다.
# 짐작으로 제약을 좁히면 만들 수 있는 메뉴를 스스로 지운다.
#
# 넣어야 하는 것이 세 가지다.
#
#   화구 1개    — 화기가 되더라도 하나뿐이라 동시 조리가 안 된다
#   냉장·냉동   — "미리 전처리해두면 괜찮다"의 실현 조건이다.
#                보관 공간이 있어야 4분 제한을 우회할 수 있다
#   리드타임    — 붕어빵기계는 대여이고 1주 전 예약이 필요하다.
#                constraints 의 "준비 3일 이내"와 정면으로 부딪힌다
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

[장비 조달]
- 붕어빵기계: 대여. 자차 이동 가능. 예약 1주 전 필요
- 화덕피자오븐 / 어묵중탕기 / 생맥주 셀프탭 / 생맥주 디스펜서:
  보유. 자차 이동 가능 (협력사 매장으로 옮겨 진행할 수 있다)"""

# 협력사 시드 데이터 — T21 협력사 입력 폼 전까지 쓰는 가상 값.
#
# 실제 협력사는 확정되었으나(자료요청서 A-4: 블랙스미스, 떡붕)
# 보유 식재료·장비는 협력사가 폼에 직접 입력할 내용이라 아직 없다.
# 실재하는 곳을 골라 그럴듯한 값을 채웠다. 8/31 이후 실제 값으로 바꾼다.
#
# 상수로 두지 않고 partners 테이블에 넣는다. 폼이 붙는 순간
# 조회 경로가 그대로 쓰이도록, 지금부터 DB 를 거쳐 읽는다.
SEED_PARTNER = {
    "name": "떡붕",
    "category": "제과·디저트",
    "signature_menu": "붕어빵",
    "ingredients": ["팥앙금", "슈크림", "붕어빵 반죽", "우유크림"],
    # 붕어빵기계는 바틀링이 대여하는 장비다(A-3). 협력사 것이 아니다.
    "equipment": ["반죽 보관용 냉장고", "제과용 소도구"],
    "collab_types": ["팝업 출장", "재료 납품", "콘텐츠 촬영"],
    "available_slots": "평일 오후 협의 가능",
    "sns_channel": "인스타그램",
    "sns_followers": 3200,
    "sns_content_type": "릴스",
    "blockers": ["반죽은 당일 소진해야 하므로 사전 대량 준비가 불가하다",
                 "주말은 자체 매장 운영으로 출장이 어렵다"],
    "invite_code": "SEED-DDUKBUNG",
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

    저가 순으로 적는다. 단가가 페어링 판단의 근거이며(명세서 1-4),
    순서가 있으면 어느 것이 고가 라인인지 LLM 이 바로 읽는다.

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

        style = r.get("style")
        if style:
            parts.append(str(style))

        # 도수 0 은 "논알콜"로 적는다. 다만 스타일이 이미 '논알콜'이면
        # 같은 말이 두 번 나오므로 생략한다.
        abv = r.get("abv")
        if abv is not None:
            if float(abv) > 0:
                parts.append(f"{_num(abv)}도")
            elif style != "논알콜":
                parts.append("논알콜")

        notes = r.get("flavor_notes") or []
        if notes:
            parts.append(", ".join(notes))

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


def build_partner_resources(partner: dict | None) -> str:
    """
    협력사가 가진 것. 셰프가 메뉴를 짜는 재료다.

    빈 항목은 줄째로 빼지 않고 "데이터 없음"으로 적는다.
    줄이 없으면 협력사가 안 가진 것인지 아직 입력하지 않은 것인지
    구분되지 않아, 없는 장비를 쓰는 메뉴가 나온다.
    """
    if not partner:
        return f"{NO_DATA} (협력사 미선택)"

    def _join(key: str) -> str:
        v = partner.get(key) or []
        return ", ".join(str(x) for x in v) if v else NO_DATA

    head = f"{partner.get('name', '?')} / {partner.get('category') or NO_DATA}"
    return "\n".join([
        head,
        f"- 대표 메뉴: {partner.get('signature_menu') or NO_DATA}",
        f"- 보유 식재료: {_join('ingredients')}",
        f"- 보유 장비: {_join('equipment')}",
        f"- 가능한 협업 형태: {_join('collab_types')}",
        f"- 가능 일정: {partner.get('available_slots') or NO_DATA}",
    ])


def build_partner_blockers(partner: dict | None) -> str:
    """
    협력사가 못 하는 것. 위반하면 그 안은 폐기된다(명세서 1-2).

    없으면 "없음"이 아니라 "데이터 없음"으로 적는다.
    입력하지 않은 것을 제약이 없는 것으로 읽으면 안 된다.
    """
    if not partner:
        return f"{NO_DATA} (협력사 미선택)"
    items = partner.get("blockers") or []
    if not items:
        return f"{NO_DATA} (협력사가 입력하지 않음)"
    return "\n".join(f"- {x}" for x in items)


def build_partner_sns(partner: dict | None) -> str:
    """(3) 마케터 입력. 팔로워 규모에 맞는 목표를 세우는 근거다."""
    if not partner:
        return f"{NO_DATA} (협력사 미선택)"
    ch = partner.get("sns_channel") or NO_DATA
    n = partner.get("sns_followers")
    kind = partner.get("sns_content_type") or NO_DATA
    n_txt = f"팔로워 {n:,}명" if n else f"팔로워 {NO_DATA}"
    return f"{ch} / {n_txt} / 주 콘텐츠 {kind}"


if __name__ == "__main__":
    print("[바틀링 맥주 라인업]")
    print(build_beer_list())
    print()
    print("[바틀링 주방 여건]")
    print(KITCHEN)

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
