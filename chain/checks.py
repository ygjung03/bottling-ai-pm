"""
생성물 검증 — 운영 경로와 테스트가 같은 검사를 쓴다

[담당] B
[티켓] T17 · 검증 루프 2단계 (docs/검증루프_도입안.md 6장)

tests/test_p4.py 안에 있던 검사를 옮겨 왔다. 테스트는 여기서 가져다 쓴다.
검사가 두 벌이 되면 갈라지고, 그러면 테스트에서 잰 통과율이 운영에서
그대로 나온다는 보장이 없어진다 (명세서 5-5 고정 테스트셋의 전제).

명세서 5-1 의 A3~A10 에 대응한다. 여기서는 판정만 한다 —
어느 것을 되감고 어느 것을 경고로 둘지는 chain/runner.py 가 정한다.
"""
import json
import re
from datetime import date

from chain.inputs import NO_DATA

# 1위 안에 반드시 있어야 하는 것.
# 대표가 이 문서만 보고 실행할 수 있어야 한다(명세서 4-2).
REQUIRED = ["메뉴명", "구성", "협력사_제공", "바틀링_준비", "보관_조건",
            "1회_납품_수량", "협력사_정가", "판매가_제안", "페어링_맥주",
            "이벤트", "홍보_일정", "홍보_문구", "실행_준비물",
            "추천_근거"]

# "정가_합" 은 여기 넣지 않는다. 세트인 안에만 있고 나머지는 null 이다.
# 맥주는 셀프탭이라 단품에서는 별개 거래다.

# 협업 제안서 4필드 (명세서 1-4, 자동 검증 A10).
# 하나라도 없으면 협력사에 보낼 제안서를 만들 수 없다 — T44 를 직접 막는다.
PROPOSAL = ["역할분담", "상호_이익", "배경", "매입"]

# 순위를 회피하는 표현.
VAGUE = re.compile(r"우열을? (?:가리기|판단하기) (?:어렵|힘들)"
                   r"|비슷하여 (?:순위|우열)"
                   r"|판단 불가")

# 제외 사유로 쓰이면 안 되는 표현.
#
# 제외는 실행이 불가능할 때만이다(검수 1·2·6번).
# "덜 매력적", "단가가 낮음", "후순위"는 3위 사유이지 제외 사유가 아니다.
# 실제로 매력도와 단가를 근거로 C안을 제외한 적이 있다.
VAGUE_EXCLUDE = re.compile(
    r"매력(?:도|이)|다양성|우위|경쟁력|후순위|밀림|떨어[지짐]|부족"
    r"|기여도 (?:측면|면)")


def is_rank_reason(why) -> bool:
    """
    안을 뺀 이유가 "만들 수 없다"가 아니라 "다른 안만 못하다"인가.

    (4)는 실행이 불가능한 안만 뺀다. 매력이 떨어진다거나 단가가 낮다는
    것은 3위를 줄 이유이지 목록에서 뺄 이유가 아니다.

    이렇게 뺀 것은 메뉴가 잘못된 것이 아니라 (4)가 잘못 판단한 것이다.
    """
    return bool(VAGUE_EXCLUDE.search(str(why or "")))


def parse_beers(text: str) -> dict[str, dict]:
    """
    맥주 라인업 문자열을 다시 구조로 되돌린다.

    프롬프트에 넣은 것과 같은 문자열을 파싱하므로,
    LLM 이 본 것과 검사가 보는 것이 어긋나지 않는다.
    """
    out = {}
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        body = line[2:]
        fixed = "[고정]" in body
        body = body.replace(" [고정]", "").replace(" [교체 가능]", "")
        parts = [p.strip() for p in body.split(" / ")]
        if len(parts) < 2:
            continue
        m = re.match(r"([\d.]+)원/ml", parts[1])
        out[parts[0]] = {
            "price": float(m.group(1)) if m else None,
            "style": parts[2] if len(parts) > 2 else "",
            "alcohol": "논알콜" not in body,
            "fixed": fixed,
        }
    return out


def parse_beer_prices(text: str) -> dict[str, float]:
    """
    맥주 라인업 문자열에서 이름과 단가만 뽑는다.

    (4)는 단가만 보므로 parse_beers() 의 결과에서 그것만 꺼낸다.
    파서를 두 벌 두면 같은 문자열을 다르게 읽을 수 있다.
    """
    return {k: v["price"] for k, v in parse_beers(text).items()
            if v["price"] is not None}


def check_final(out: dict, p2: dict, beers: dict) -> list[str]:
    """프롬프트가 지시한 제약을 지켰는지 본다."""
    issues = []

    ranks = out.get("순위") or []
    excluded = out.get("제외") or []
    p2_ids = {m.get("안_id") for m in (p2.get("메뉴안") or [])}

    if out.get("재생성_필요"):
        if ranks:
            issues.append("재생성 필요인데 순위가 있음")
        return issues

    if not ranks:
        issues.append("순위 없음")

    # 모든 안이 순위나 제외 중 한쪽에 있어야 한다
    seen = {r.get("안_id") for r in ranks} | {e.get("안_id") for e in excluded}
    missing = p2_ids - seen
    if missing:
        issues.append(f"순위·제외 어디에도 없는 안: {sorted(missing)}")

    # 제외는 실행 불가일 때만이다.
    # 덜 매력적이라거나 단가가 낮다는 것은 3위 사유이지 제외 사유가 아니다.
    for e in excluded:
        why = str(e.get("제외_사유") or "")
        if VAGUE_EXCLUDE.search(why):
            issues.append(f"{e.get('안_id')}: 순위를 낮출 이유인데 안을 "
                          f"아예 뺐다 — {why[:40]}")

    # 순위는 1부터 빠짐없이
    nums = sorted(r.get("순위") for r in ranks if r.get("순위"))
    if nums != list(range(1, len(ranks) + 1)):
        issues.append(f"순위 번호 이상: {nums}")

    # 메뉴를 새로 만들지 않았는가
    p2_names = {m.get("메뉴명") for m in (p2.get("메뉴안") or [])}
    for r in ranks:
        if r.get("메뉴명") and r["메뉴명"] not in p2_names:
            issues.append(f"{r.get('안_id')}: (2)에 없는 메뉴명 '{r['메뉴명']}'")

        # 단가를 옮겨 적다 틀리는 일이 있다.
        # 카이저돔 16원을 20원으로, 37디그리스 14원을 8원으로 적은 적이 있다.
        pair = r.get("페어링_맥주") or {}
        name, price = pair.get("메뉴명"), pair.get("원_ml")
        if name and name not in beers:
            issues.append(f"{r.get('안_id')}: 라인업에 없는 맥주 '{name}'")
        elif name and price is not None and float(price) != beers[name]:
            issues.append(f"{r.get('안_id')}: {name} 단가 틀림 "
                          f"({price} → {beers[name]:.0f} 이어야 함)")

    # 1위는 그대로 실행할 수 있어야 한다
    if ranks:
        top = next((r for r in ranks if r.get("순위") == 1), ranks[0])
        for k in REQUIRED:
            v = top.get(k)
            if not v:
                issues.append(f"1위에 '{k}' 없음")

        basis = top.get("추천_근거") or {}
        for k in ("상권_지표", "자원_매칭"):
            if not basis.get(k):
                issues.append(f"1위 추천 근거에 '{k}' 없음")

        # A10 — 협업 제안서 4필드. 없으면 T44 가 만들 것이 없다.
        for k in PROPOSAL:
            if not top.get(k):
                issues.append(f"1위에 제안서 필드 '{k}' 없음")

        roles = top.get("역할분담") or {}
        for side in ("바틀링", "협력사"):
            if not roles.get(side):
                issues.append(f"1위 역할분담에 '{side}' 없음")

        # 한쪽만 이득이면 협업이 성사되지 않는다
        gains = top.get("상호_이익") or {}
        for side in ("바틀링", "협력사"):
            if not gains.get(side):
                issues.append(f"1위 상호 이익에 '{side}' 없음")

        # 매입가는 AI 가 정할 값이 아니다. 항상 협의 대상이다 (명세서 1-4 ④)
        deal = top.get("매입") or {}
        for k in ("바틀링_제안_매입가", "근거"):
            if not deal.get(k):
                issues.append(f"1위 매입에 '{k}' 없음")
        if deal and deal.get("협의_필요") is not True:
            issues.append(f"1위 매입의 협의_필요가 {deal.get('협의_필요')} "
                          f"— 항상 true 여야 한다")

        # 대표님이 이 숫자를 들고 협상하신다. 어디서 나온 값인지 보여야 한다.
        why = deal.get("근거")
        if why is not None and not isinstance(why, dict):
            issues.append(f"1위 매입 근거가 자유 문장임 — 세 갈래로 나눠야 함: {str(why)[:40]}")
        elif isinstance(why, dict):
            for k in ("협력사_희망", "협력사정가_대비", "소비_근거"):
                if not why.get(k):
                    issues.append(f"1위 매입 근거에 '{k}' 없음")
            # 협력사 제조 원가는 우리가 모른다. 모른다고 적혀야 정직하다.
            if not (why.get("미확인") or []):
                issues.append("1위 매입 근거에 미확인 항목이 비었음 "
                              "— 협력사 실제 원가를 안다고 말하는 셈이다")

        # 2·3위에는 쓰지 않는다. 출력이 세 배가 되고, 실제로 보내는 것은
        # 채택된 안 하나다.
        for r in ranks:
            if r is top:
                continue
            extra = [k for k in PROPOSAL if r.get(k)]
            if extra:
                issues.append(f"{r.get('안_id')}({r.get('순위')}위): "
                              f"1위 전용 필드가 채워짐 {extra}")

    # 후순위 사유가 있어야 한다
    for r in ranks:
        if r.get("순위") != 1 and not r.get("선정_사유"):
            issues.append(f"{r.get('안_id')}: 후순위 사유 없음")
        if not (r.get("예상_리스크") or []):
            issues.append(f"{r.get('안_id')}: 예상 리스크 없음")

    for e in excluded:
        if not e.get("제외_사유"):
            issues.append(f"{e.get('안_id')}: 제외 사유 없음")

    # 검수 결과를 남겼는가
    if not (out.get("체크리스트") or []):
        issues.append("체크리스트 없음")

    # 순위를 회피하지 않았는가
    if VAGUE.search(json.dumps(out, ensure_ascii=False)):
        issues.append("순위 판단을 회피하는 표현 사용")

    return issues


# ════════════════════════════════════════════════════════════
# (2) 셰프 — 메뉴 3안
# ════════════════════════════════════════════════════════════

# 완제품 매입 단일화로 사라진 필드 (명세서 1-2).
# 남아 있으면 프롬프트에 옛 지시가 붙어 있다는 뜻이다.
COOKING_FIELDS = ["조리_방법", "조리_주체", "조리_난이도", "필요_장비", "필요_재료"]

# 「접근」은 조리 방식이 아니라 구성과 가격대로 나뉜다.
APPROACHES = {"단품", "세트", "원가 절감형"}


def check_menu(out: dict, beers: dict) -> list[str]:
    """프롬프트가 지시한 제약을 지켰는지 본다."""
    issues = []
    menus = out.get("메뉴안") or []

    if len(menus) != 3:
        issues.append(f"메뉴안 {len(menus)}개 — 3개여야 함")

    ids = [m.get("안_id") for m in menus]
    if len(set(ids)) != len(ids):
        issues.append(f"안_id 중복: {ids}")

    approaches = [m.get("접근") for m in menus]
    if len(set(approaches)) != len(approaches):
        issues.append(f"접근이 중복됨: {approaches}")
    unknown = [a for a in approaches if a not in APPROACHES]
    if unknown:
        issues.append(f"정의에 없는 접근 {unknown} — {sorted(APPROACHES)} 중이어야 함")

    picked_prices = []

    for m in menus:
        mid = m.get("안_id", "?")

        # 조리가 없어졌는데 필드가 남아 있으면 옛 프롬프트다
        left = [k for k in COOKING_FIELDS if m.get(k)]
        if left:
            issues.append(f"{mid}: 사라진 조리 필드가 남아 있음 {left}")

        # 페어링은 라인업 안에서, 알코올 중에서
        pair = (m.get("페어링_맥주") or {}).get("메뉴명")
        if not pair:
            issues.append(f"{mid}: 페어링 맥주 없음")
        elif pair not in beers:
            issues.append(f"{mid}: 라인업에 없는 맥주 '{pair}'")
        else:
            if not beers[pair]["alcohol"]:
                issues.append(f"{mid}: 논알콜 페어링 '{pair}'")
            picked_prices.append(beers[pair]["price"])

        reason = (m.get("페어링_맥주") or {}).get("선정_이유") or ""
        if len(reason) < 15:
            issues.append(f"{mid}: 페어링 이유가 너무 짧음")

        # 누가 무엇을 대는지 나뉘어 있는가.
        # 협력사가 완제품을 내지 않으면 매입할 것이 없어 협업이 아니다.
        if not (m.get("협력사_제공") or []):
            issues.append(f"{mid}: 협력사 제공 품목 없음 — 매입할 것이 없다")
        if not (m.get("바틀링_준비") or []):
            issues.append(f"{mid}: 바틀링 준비 항목 없음")

        # 완제품 조건. 보관 방법과 유통 기한이 기획의 전제다 (C006)
        if not m.get("보관_조건"):
            issues.append(f"{mid}: 보관 조건 없음")
        if not m.get("1회_납품_수량"):
            issues.append(f"{mid}: 1회 납품 수량 없음")

        # 매입가·판매가.
        #
        # 원가율 40% 검사는 뺐다(명세서 5-1). 매입 형태에서 매입가는
        # 협력사와 협의할 값이라 40% 라는 기준에 근거가 없다.
        # 대신 손익 역전만 막는다 (A6).
        cost, price = m.get("협력사희망_매입가"), m.get("판매가_제안")
        if not price:
            issues.append(f"{mid}: 판매가 미제시 (매입가와 별개로 정해야 함)")

        # 무엇에 근거했는지 밝혀야 한다. 마진 기준값 3건에만 기대면
        # 근거가 얇다 — 형태가 다른 값이라 참고 이상이 못 된다 (U18).
        basis = str(m.get("판매가_근거") or "")
        if not basis:
            issues.append(f"{mid}: 판매가 근거 없음")
        elif not re.search(r"\d", basis):
            issues.append(f"{mid}: 판매가 근거에 수치가 없음 — {basis[:40]}")
        if isinstance(cost, str) and "산출 불가" not in cost:
            n = re.search(r"([\d,]+)", cost)
            if n and price:
                c = int(n.group(1).replace(",", ""))
                if c >= price:
                    issues.append(f"{mid}: 매입가 {c:,}원 ≥ 판매가 {price:,}원"
                                  f" — 손익 역전")

        # 협력사 매장에서 사는 값. 매입가를 제안할 때 이것과 견준다.
        if not m.get("협력사_정가"):
            issues.append(f"{mid}: 협력사 정가 없음 — 매입가를 견줄 기준이 없다")

        # 맥주값을 넣는 것은 세트뿐이다.
        #
        # 셀프탭이라 손님이 300ml 만 마실 수도 1L 를 마실 수도 있어, 맥주를
        # 늘 500ml 로 묶으면 그 방식이 깨진다. 예전에 이 구분이 없어서
        # 판매가가 어떤 때는 안주 값이고 어떤 때는 맥주 포함 값이었고,
        # 화면이 늘 안주 값으로 보고 맥주를 한 번 더 더했다.
        listed = m.get("정가_합")
        is_set = m.get("접근") == "세트"

        if is_set and not listed:
            issues.append(f"{mid}: 세트인데 정가 합이 없음")
        if not is_set and listed:
            issues.append(f"{mid}: 세트가 아닌데 정가 합이 있음 ({listed:,}원)"
                          f" — 맥주는 별개 거래다")

        # 세트는 따로 사는 것보다 싸야 한다. 값이 같으면 묶을 이유가 없다.
        if is_set and listed and price:
            if price >= listed:
                issues.append(f"{mid}: 세트가 {price:,}원 ≥ 정가 합 "
                              f"{listed:,}원 — 할인이 없다")

        # 이미지는 이 단계 다음에 별도로 생성된다 (명세서 1-2 ④)
        if m.get("메뉴_이미지"):
            issues.append(f"{mid}: 메뉴 이미지를 지어냄 — 별도 단계에서 생성한다")

        if not m.get("제약_충족_확인"):
            issues.append(f"{mid}: 제약 충족 확인 누락")

    # 세 안이 모두 저가 라인에 몰리지 않아야 한다
    known = [p for p in picked_prices if p is not None]
    if len(known) == 3 and max(known) <= 14:
        issues.append(f"페어링이 모두 저가 라인 {known}")

    return issues


# 메뉴명·구성에 나오면 곤란한 재료.
#
# 협력사·바틀링 어느 목록에도 없는데 등장한 적이 있는 것들이다.
# 실제로 "붕어빵 아이스크림 플레이트"가 나왔으나 아이스크림은
# 어디에도 없었다. 목록을 전부 열거할 수는 없으므로,
# 겪은 것부터 하나씩 쌓는다.
GHOST = ["아이스크림", "생크림", "치즈", "베이컨", "시럽", "잼", "초콜릿"]


def check_menu_sources(out: dict, partner: dict) -> list[str]:
    """
    메뉴명·구성에 나온 재료가 어디서 오는지 본다 (프롬프트 규칙 8).

    올 곳은 둘뿐이다 — 협력사가 납품하는 메뉴, 그리고 바틀링이 준비하는 것.
    둘 다 아니면 아무도 준비하지 않는 재료라 그 안은 실행되지 않는다.
    """
    sold = " ".join(str(m.get("메뉴") or "")
                    for m in (partner.get("menu_prices") or []))
    base = f"{sold} {partner.get('signature_menu') or ''}"

    issues = []
    for m in out.get("메뉴안") or []:
        text = f"{m.get('메뉴명', '')} {m.get('구성', '')}"
        prep = " ".join(str(x) for x in (m.get("바틀링_준비") or []))
        have = f"{base} {prep}"
        for g in GHOST:
            if g in text and g not in have:
                issues.append(f"{m.get('안_id', '?')}: '{g}' 가 어디서 오는지 "
                              f"없음 — 바틀링_준비에 적혀야 한다")
    return issues


# ════════════════════════════════════════════════════════════
# (3) 마케터 — 홍보 기획
# ════════════════════════════════════════════════════════════

# 도달·노출 목표에 쓰이는 수치 표현.
#
# 이런 값을 우리가 측정하지 않으므로 목표로 쓸 수 없다. 달성했는지
# 확인할 방법이 없다. 목표는 팔린 수량으로 쓴다 (프롬프트 규칙 3).
#
# 어순이 양쪽으로 나타난다. "도달 10,000명"도 "10,000명 도달"도 쓰인다.
KEYWORD = r"도달|노출|조회|좋아요|팔로워|저장|공유|유입|방문자"
REACH = re.compile(
    rf"(?:{KEYWORD})\s*\d[\d,]*"      # 도달 10,000
    rf"|\d[\d,]*\s*[명회건%]?\s*(?:{KEYWORD})"   # 10,000명 도달
)

# 문구가 아니라 문구에 대한 설명일 때 나타나는 표현.
# "~를 강조하는 문구" 같은 것은 그대로 게시할 수 없다.
NOT_A_COPY = re.compile(r"(?:하는|강조|어필|소구|담은|활용한|중심의)\s*"
                        r"(?:문구|카피|메시지|내용)")

# 타겟이 사람이 아니라 통계일 때 나타나는 형태.
# "20대 21% / 40대 18%" 처럼 비중을 옮겨 적으면 홍보 대상이 아니다.
STAT_TARGET = re.compile(r"\d+대\s*\d+%.*?\d+대\s*\d+%")

# 준비물에 들어오면 안 되는 것 — 조리·보관 장비.
# 협업이 완제품 매입 하나이므로 바틀링은 조리하지 않는다.
# (3)의 준비물은 홍보·이벤트 실행에 새로 챙길 것
# (포장재·홍보물·촬영 소품 등)이어야 한다.
OWNED = ["냉장고", "냉동", "전자레인지", "화덕", "오븐", "그릴",
         "어묵중탕기", "착즙기", "셀프탭", "디스펜서", "소도구"]

# 장비 이름이 들어 있어도 인쇄물이면 준비물로 맞다.
# "셀프탭 맥주 제공 환경 확인용 안내물"을 장비로 잡은 적이 있다 —
# 장비가 아니라 그 장비를 설명하는 인쇄물이다.
PROMO_ITEM = re.compile(r"안내물|안내판|포스터|홍보물|게시물|전단|스티커"
                        r"|배너|현수막|메뉴판|쿠폰|카드")

# 홍보 일정의 "실행 전" 시점. C001·C002 의 자동 검사다 (명세서 5-1 A7).
# 실행 기간에만 알리면 사람들이 알기 전에 끝난다 — 카페 협업이 그랬다.
BEFORE_EXEC = re.compile(r"전|예고|티저|D-\s*\d")

# 실행 기간을 며칠로 잡았는지. C003 의 자동 검사다 (A8).
MIN_DAYS = 3


def duration_days(text: str) -> int | None:
    """
    "9/5(금)～9/7(일) 3일간" 같은 표기에서 일수를 뽑는다.

    "3일간"이 있으면 그대로 쓰고, 없으면 날짜 범위로 센다.
    둘 다 없으면 None — 판정하지 않는다. 근거 없이 위반으로 몰지 않는다.
    """
    named = re.findall(r"(\d+)\s*일간?", text)
    if named:
        return max(int(x) for x in named)

    md = re.findall(r"(\d{1,2})/(\d{1,2})", text)
    if len(md) >= 2:
        try:
            a = date(2026, int(md[0][0]), int(md[0][1]))
            b = date(2026, int(md[-1][0]), int(md[-1][1]))
        except ValueError:
            return None
        return (b - a).days + 1 if b >= a else None
    return None


def span_start(text: str, year: int) -> date | None:
    """
    "2026-09-17(목)~2026-09-19(토) 3일간" 같은 표기에서 시작일을 뽑는다.

    "9/17(목)~" 처럼 연도가 빠진 표기가 흔하다. 이때는 인자로 받은
    year, 즉 대상일의 연도를 쓴다.

    날짜를 찾지 못하면 None 을 돌려준다. "3일간"처럼 일수만 적힌 경우가
    여기 해당하며, 근거가 없으므로 위반으로 몰지 않는다.
    """
    m = re.search(r"(?:(\d{4})\s*[-./년]\s*)?(\d{1,2})\s*[-./월]\s*(\d{1,2})", text)
    if not m:
        return None
    try:
        return date(int(m.group(1) or year), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def check_promo(out: dict, p2: dict, target: date,
          partner_sns: bool = True) -> list[str]:
    """
    프롬프트가 지시한 제약을 지켰는지 본다.

    partner_sns: 협력사가 SNS 를 운영하는가.
      없으면 협력사에 홍보를 요청하지 않는 것이 맞다 (규칙 10).
      판매가 바틀링 매장에서 이뤄지므로 협력사 매장 게시물로 얻는 것이
      불확실하고, 없는 채널을 대신할 것을 만들면 부담만 늘어난다.
    """
    issues = []

    axis = out.get("공통_홍보축") or {}
    if not axis:
        issues.append("공통 홍보축 없음")
    else:
        for k in ("타겟", "공략_시점", "채널별_전략"):
            if not axis.get(k):
                issues.append(f"공통 홍보축에 '{k}' 없음")

        # 타겟은 사람이어야 한다. 비중 나열은 홍보 대상이 아니다.
        tgt = str(axis.get("타겟") or "")
        if STAT_TARGET.search(tgt):
            issues.append(f"타겟이 통계 나열임 — {tgt[:40]}")

        # A7 — 홍보 일정에 실행 전 항목이 하나 이상 (C001·C002)
        schedule = axis.get("홍보_일정") or []
        if not schedule:
            issues.append("홍보 일정 없음 — 언제 무엇을 올리는지가 있어야 한다")
        else:
            for s in schedule:
                for k in ("시점", "채널", "내용"):
                    if not s.get(k):
                        issues.append(f"홍보 일정 항목에 '{k}' 없음: {s}")
            # 시점은 "실행 1주 전" 같은 상대 표현으로도, "2026-09-03" 같은
            # 실제 날짜로도 온다. 실행일을 알려준 뒤로는 날짜 쪽이 많다.
            #
            # 날짜가 적혀 있으면 그것으로 판정한다. 실행일 당일이나 그 뒤는
            # 사전 홍보가 아니다. 날짜가 없을 때만 표현을 본다.
            def is_before(s) -> bool:
                when = str(s.get("시점") or "")
                day = span_start(when, target.year)
                if day:
                    return day < target
                return bool(BEFORE_EXEC.search(when))

            if not any(is_before(s) for s in schedule):
                when = [str(s.get("시점")) for s in schedule]
                issues.append(f"홍보 일정에 '실행 전' 항목 없음 — {when}")

        # A9 — 채널별 전략에 협력사 주체가 하나 이상
        channels = axis.get("채널별_전략") or []
        for c in channels:
            if not c.get("주체"):
                issues.append(f"채널별 전략에 '주체' 없음: {c}")
        has_partner = any(c.get("주체") == "협력사" for c in channels)
        if partner_sns and not has_partner:
            issues.append("채널별 전략에 협력사 주체 없음 — "
                          "함께 올리면 같은 노력으로 두 배가 닿는다")
        if not partner_sns and has_partner:
            issues.append("협력사에 SNS 가 없는데 협력사 주체 항목을 넣었다")

    plans = out.get("안별_기획") or []
    p2_ids = [m.get("안_id") for m in (p2.get("메뉴안") or [])]
    p3_ids = [p.get("안_id") for p in plans]

    if len(plans) != len(p2_ids):
        issues.append(f"안별 기획 {len(plans)}개 — 메뉴안 {len(p2_ids)}개와 불일치")
    if set(p3_ids) != set(p2_ids):
        issues.append(f"안_id 불일치: (2){p2_ids} vs (3){p3_ids}")

    goal = str(axis.get("목표") or "")
    if REACH.search(goal):
        issues.append(f"측정하지 않는 값을 목표로 삼음: {goal[:40]}")

    for p in plans:
        pid = p.get("안_id", "?")

        ev = p.get("이벤트안") or {}
        for k in ("명칭", "내용", "기간"):
            v = ev.get(k)
            if not v:
                issues.append(f"{pid}: 이벤트안에 '{k}' 없음")
            elif NO_DATA in str(v):
                issues.append(f"{pid}: 이벤트안 '{k}'가 데이터 없음 — 마케터가 정할 값이다")

        # A8 — 실행 기간 3일 이상 (C003)
        span = str(ev.get("기간") or "")
        days = duration_days(span)
        if days is not None and days < MIN_DAYS:
            issues.append(f"{pid}: 실행 기간 {days}일 — {MIN_DAYS}일 이상이어야 함")

        # 기간이 실행 예정일부터 시작하는가.
        #
        # (3)이 실행일을 몰라 스키마 예시를 그대로 베끼거나 엉뚱한 달을
        # 지어낸 적이 있다. 이 값은 제안서에 그대로 실려 협력사에 나간다.
        start = span_start(span, target.year)
        if start and start != target:
            issues.append(f"{pid}: 실행 기간이 대상일부터 시작하지 않음 "
                          f"— 대상 {target} / 기간 '{span}'")

        copy = str(p.get("홍보_문구") or "")
        if not copy:
            issues.append(f"{pid}: 홍보 문구 없음")
        elif NOT_A_COPY.search(copy):
            issues.append(f"{pid}: 문구가 아니라 설명임 — {copy[:30]}")
        elif len(copy) < 15:
            issues.append(f"{pid}: 홍보 문구가 너무 짧음")

        tags = p.get("해시태그") or []
        if not tags:
            issues.append(f"{pid}: 해시태그 없음")
        elif any(not str(t).startswith("#") for t in tags):
            issues.append(f"{pid}: '#' 없는 해시태그 {tags}")

        for k in ("차별_포인트", "준비물"):
            v = p.get(k)
            if not v:
                issues.append(f"{pid}: '{k}' 없음")
            elif NO_DATA in str(v):
                issues.append(f"{pid}: '{k}'가 데이터 없음 — 마케터가 정할 값이다")

        # 준비물은 홍보·이벤트용이어야 한다. 조리 장비는 (2)의 몫이다.
        for item in p.get("준비물") or []:
            if PROMO_ITEM.search(str(item)):
                continue
            hit = next((o for o in OWNED if o in str(item)), None)
            if hit:
                issues.append(f"{pid}: 조리 장비를 준비물로 적음 — '{item}'")

    # 우열을 매기지 않아야 한다
    text = json.dumps(out, ensure_ascii=False)
    for w in ("1순위", "2순위", "3순위", "가장 추천", "최우선", "베스트"):
        if w in text:
            issues.append(f"우열 표현 '{w}' 사용")

    return issues
