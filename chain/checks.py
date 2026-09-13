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

# 1위 안에 반드시 있어야 하는 것.
# 대표가 이 문서만 보고 실행할 수 있어야 한다(명세서 4-2).
REQUIRED = ["메뉴명", "구성", "협력사_제공", "바틀링_준비", "보관_조건",
            "1회_납품_수량", "협력사_정가", "판매가_제안", "페어링_맥주",
            "이벤트", "홍보_일정", "홍보_문구", "실행_준비물", "소요_기간",
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


def parse_beer_prices(text: str) -> dict[str, float]:
    """맥주 라인업 문자열에서 이름과 단가를 뽑는다."""
    out = {}
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        parts = [p.strip() for p in line[2:].split(" / ")]
        if len(parts) < 2:
            continue
        m = re.match(r"([\d.]+)원/ml", parts[1])
        if m:
            out[parts[0]] = float(m.group(1))
    return out


def check(out: dict, p2: dict, beers: dict) -> list[str]:
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
            issues.append(f"{e.get('안_id')}: 순위 사유로 제외함 — {why[:40]}")

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
