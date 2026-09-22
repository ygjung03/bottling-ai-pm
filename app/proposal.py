"""
협업 제안서 생성 — 협력사에 그대로 보내는 문서 (T44, 명세서 1-4)

[담당] B

화면에서 떼어 둔 이유는 이 문서가 밖으로 나가기 때문이다. Streamlit 을
띄우지 않고 검증할 수 있어야 `tests/test_proposal.py` 가 실제 체인 출력으로
문서를 만들어 볼 수 있다. 화면(`app/pages/2_기획안_생성.py`)은 여기서 만든
것을 그리기만 한다.

[새로 만드는 내용이 없다]
  (4) 컨설턴트가 각 안에 채운 역할분담·상호_이익·배경·매입을 옮겨 담을
  뿐이다. 여기서 문장을 지어내면 화면에 보이는 것과 협력사가 받는 것이
  달라진다.

[어느 안이든 제안서가 된다]
  9/19 부터 (4)는 순위를 매기지 않는다. 대표가 세 안 중 하나를 고르고
  그 안이 제안서가 되므로, 어느 안을 넣어도 이 함수가 동작해야 한다.
"""
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))


def _cols(s: str) -> int:
    """
    고정폭으로 보일 때 차지하는 칸 수.

    한글·한자는 두 칸을 차지하는데 len() 은 한 칸으로 센다. 그대로 줄을
    맞추면 항목 이름의 길이에 따라 값이 들쭉날쭉해진다. 복사용 본문도
    Word 도 고정폭으로 읽히므로 여기서 맞춰야 한다.
    """
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _cols(s))


def won(text) -> int | None:
    """
    "1500원", "1800원 — 협력사 정가 3000원 대비 60%" 에서 앞의 금액을 뽑는다.

    "산출 불가" 나 숫자가 없는 문장이면 None. 모르는 값을 0 으로 두면
    협력사에 주는 돈이 없는 것처럼 보인다.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    m = re.search(r"(\d[\d,]*)", str(text))
    return int(m.group(1).replace(",", "")) if m else None


def end_dot(text) -> str:
    """
    문장 끝에 마침표를 붙인다. LLM 이 "~합니다" 로 끝내면서 마침표를 자주
    빠뜨린다 (9/21 화면 확인). "다" 로 끝날 때만 붙인다 — 명사로 끝나는
    항목은 그대로 둔다.
    """
    if not text:
        return ""
    s = str(text).strip()
    return s + "." if s.endswith("다") else s


def proposal_no(meta: dict) -> str:
    """
    문서번호. 협력사가 받는 문서라 어느 건인지 가리킬 수 있어야 한다.

    plans.id 를 쓴다. 저장에 실패했으면 번호를 지어내지 않고 초안으로 표시한다.
    번호가 있는데 DB 에 없는 문서가 돌아다니면 나중에 대조가 안 된다.
    """
    pid = meta.get("plan_id")
    year = datetime.now(KST).year
    return f"BTL-{year}-{pid:04d}" if pid else f"BTL-{year}-초안"


BOTTLING_ADDRESS = "서울 광진구 뚝섬로34길 67"

# 바틀링 소개. 1차 제안서에만 들어간다 — 아직 우리를 모르는 상대에게 보내는
# 문서라서다. 여기 적힌 것은 전부 확인된 사실이어야 한다 (사용자 확인 2026-09-22).
BOTTLING_INTRO = [
    "바틀링은 서울 광진구 자양동, 뚝섬한강공원 인근에 있는 셀프탭 크래프트 맥주 펍입니다.",
    "자양역 1번 출구에서 도보 1분 거리에 있어 매장을 찾기 쉽습니다.",
    "12개의 셀프탭에서 원하는 만큼 맥주를 직접 따라 마시고, 마신 양만큼 결제합니다.",
    "50ml 이내는 무료로 시음할 수 있어 여러 크래프트 맥주를 맛본 뒤 원하는 맥주를 고를 수 있습니다.",
    "크래프트 맥주 12종과 다양한 안주를 함께 판매하며, 내외부 좌석에서 대화를 나누기 좋고 "
    "테이크아웃으로도 이용합니다.",
    "한강 인근에 있어 러너들도 자주 이용하는 매장입니다.",
]

# 6절 첫 줄. 소개에 섞여 있던 제안 문장을 제안하는 자리로 옮겼다 (9/22).
OFFER_LEAD = ("협력사는 기존 메뉴를 그대로 만들어 주시면 됩니다. 별도의 조리 부담 없이 "
              "새로운 판매 공간에서 메뉴를 소개할 수 있습니다.")

# 1차 제안서의 고정 문구 (9/21 검토 반영). 모르는 상대라 "작게 해 보자" 는 틀과,
# 협력사 이름이 어디에 어떻게 나오는지를 제안 수준으로 적는다. 여기 적힌 것은
# 바틀링이 실제로 해 줄 수 있는 것이어야 한다 — 대표 확인 대상.
PILOT_LINE = ("먼저 짧게 시범으로 해 보고, 손님 반응을 보고 이어갈지 함께 정하는 것을 "
              "제안드립니다.")
EXPOSURE_OFFER = [
    "매장 메뉴판과 현장 게시물에 협력사 상호 표기",
    "바틀링 인스타그램 게시물에 협력사 계정 태그",
    "판매 기간이 끝나면 판매량과 손님 반응 공유",
]

# 접근별 판매 방식. 협력사에게 "손님에게 어떻게 팔리나" 를 한 줄로.
SALE_STYLE = {
    "단품": "안주 단품으로 판매합니다. 맥주는 손님이 셀프탭에서 따로 따릅니다.",
    "세트": "안주와 맥주 500ml를 세트로 묶어 판매합니다.",
    "포장": "가져가서 먹는 구성으로 판매합니다. 맥주도 원하는 만큼 담아 갈 수 있습니다.",
}


def _sections(item: dict, meta: dict) -> list[dict]:
    """
    제안서를 절 목록으로 만든다. 텍스트·Word·화면 미리보기가 이것을 각각 그린다.

    절은 {"title": ..., "items": [(항목, 값) | 문장 | ("-", 글머리)] } 다.
      (항목, 값) 쌍은 "• 항목   값" 줄로, 문자열은 문단으로 그린다.

    1차(협력사가 아직 우리를 모른다)와 2차(폼을 받고 협의 중)가 다르다.
      1차  우리가 누구인지 → 왜 이 가게에 → 무엇을 → 하면 어떻게 되나 → 어떻게 답하나.
           매입가 숫자·탈락 안·검수·리스크·가격 근거는 넣지 않는다. 서명란 없음.
      2차  조건(매입가 숫자 포함)과 협의 사항을 적고 서명란을 둔다.

    [시안의 수익 배분은 쓰지 않는다] 시안(docs/ref)은 세 상점이 세트를 만들어
      수익을 나누는 구조다. 우리는 완제품을 매입해 파는 구조라(기획서 6-1) 나눌
      비율이 없고 매입가 하나가 협의 대상이다.
    """
    first = (meta.get("round") or 1) == 1
    partner = meta.get("partner_name") or "협력사"
    deal = item.get("매입") or {}
    basis = deal.get("근거") if isinstance(deal.get("근거"), dict) else {}
    roles = item.get("역할분담") or {}
    gains = item.get("상호_이익") or {}
    ev = item.get("이벤트") or {}
    beer = item.get("페어링_맥주") or {}
    approach = item.get("접근") or ""
    set_price = item.get("판매가_제안")
    listed = item.get("정가_합")
    menu = item.get("메뉴명") or ""

    out: list[dict] = []

    # Ⅰ. 한눈에 보기
    #
    # 맥주 라벨은 접근에 따라 다르다. 단품·포장은 맥주가 값에 안 들어가는데
    # "함께 내는 맥주" 라 쓰면 세트처럼 읽힌다 (9/21 검토).
    # 실행일과 판매 기간을 나눠 적는다 — 실행일은 시작일이고 판매는 이벤트
    # 기간(3일 이상, C003) 동안이라 하루짜리로 읽히면 납품 수량 판단이 틀어진다.
    beer_line = beer.get("메뉴명") or "데이터 없음"
    beer_label = "함께 내는 맥주" if approach == "세트" else "추천 맥주"
    glance: list = [
        ("제안 메뉴", menu),
        (beer_label, beer_line),
        ("협업 방식", "협력사 완제품을 바틀링이 매입해 판매"),
        ("시작일", meta.get("target_date") or ""),
    ]
    if ev.get("기간"):
        glance.append(("판매 기간", ev["기간"]))
    out.append({"title": "협업 제안 한눈에 보기", "items": glance})

    if first:
        out.append({"title": "바틀링 소개", "items": list(BOTTLING_INTRO)})

    # Ⅲ. 이유 — (4)의 배경(상권 근거로 쓴 문장)
    if item.get("배경"):
        out.append({"title": "이번 협업을 제안한 이유", "items": [end_dot(item["배경"])]})

    # Ⅳ. 메뉴 — 메뉴명은 Ⅰ에 있으니 여기선 구성부터. 단품은 구성이 메뉴명과
    # 같아("소보로빵 1개") 두 번 나오므로 뺀다.
    why = f" — {end_dot(beer['이유'])}" if beer.get("이유") else ""
    menu_items: list = []
    if approach != "단품" and item.get("구성"):
        menu_items.append(("구성", item["구성"]))
    menu_items += [
        (beer_label, f"{beer_line}{why}"),
        ("판매 방식", SALE_STYLE.get(approach, "")),
    ]
    if listed and set_price:
        menu_items.append(("바틀링 판매가", f"{set_price:,}원 (따로 사면 {listed:,}원)"))
    elif set_price:
        menu_items.append(("바틀링 판매가", f"{set_price:,}원"))
    out.append({"title": "협업 메뉴 제안", "items": menu_items})

    # Ⅴ. 홍보 — 실행 전 시점이 문서에 없으면 실행 전에 안 올라간다 (1-5)
    promo: list = []
    if ev.get("명칭"):
        promo += [("이벤트", ev["명칭"]), ("내용", end_dot(ev.get("내용"))),
                  ("기간", ev.get("기간") or "협의 필요")]
    for s in item.get("홍보_일정") or []:
        if s.get("시점"):
            promo.append((str(s["시점"]), f"{s.get('채널') or ''} — {s.get('내용') or ''}"))
    if item.get("홍보_문구"):
        promo.append(("홍보 문구(안)", item["홍보_문구"]))
    if promo:
        out.append({"title": "홍보 및 판매 방식", "items": promo})

    # Ⅵ. 제안 내용 — 1차는 매입가 숫자 없이 "협의"
    offer: list = [
        ("협력사가 준비", " / ".join(item.get("협력사_제공") or []) or "데이터 없음"),
        ("바틀링이 준비", " / ".join(item.get("바틀링_준비") or []) or "데이터 없음"),
        ("협력사가 얻는 것", end_dot(gains.get("협력사")) or "데이터 없음"),
        ("바틀링이 얻는 것", end_dot(gains.get("바틀링")) or "데이터 없음"),
    ]
    if first:
        # 모르는 상대에게는 "작게 해 보자" 는 틀이 문턱을 낮춘다. 협력사가 얻는
        # 것도 "홍보 효과" 가 아니라 이름이 어디에 어떻게 나오는지로 적는다
        # (9/21 검토 — 블랙스미스 제안서와 비교). 확정이 아니라 제안이다.
        offer = ([OFFER_LEAD, PILOT_LINE] + offer
                 + [("매입가", "협의해서 정합니다."),
                    ("납품 수량·보관", "협의해서 정합니다."),
                    "협력사 이름은 이렇게 알리겠습니다 (제안):"]
                 + [("-", x) for x in EXPOSURE_OFFER])
        out.append({"title": "협력사에 제안하는 내용", "items": offer})
    else:
        if deal.get("바틀링_제안_매입가"):
            amount = won(deal["바틀링_제안_매입가"])
            shown = f"{amount:,}원" if amount else str(deal["바틀링_제안_매입가"])
            offer.append(("제안 매입가", f"{shown}  ※ 협의 필요" if deal.get("협의_필요") else shown))
        if deal.get("협력사_수익"):
            offer.append(("협력사 수익", deal["협력사_수익"]))
        offer += [("보관 조건", item.get("보관_조건") or "협의 필요"),
                  ("1회 납품 수량", item.get("1회_납품_수량") or "협의 필요")]
        role_lines = [(side, " / ".join(roles.get(side) or []) or "데이터 없음")
                      for side in ("바틀링", "협력사")]
        out.append({"title": "역할과 조건", "items": role_lines + offer})

        todo = list(basis.get("미확인") or [])
        if deal.get("협의_필요"):
            todo.append("매입가 최종 확정")
        for label, key in [("1회 납품 수량", "1회_납품_수량"), ("보관 조건", "보관_조건")]:
            v = str(item.get(key) or "")
            if "협의" in v or "확인" in v:
                todo.append(label)
        if todo:
            out.append({"title": "협의가 필요한 사항", "items": [("-", x) for x in todo]})

    # Ⅶ. 다음 단계 — 회신 → 조건 확정 → 홍보 시작 → 판매 → 결과 공유.
    # 회신 기한이 없으면 협력사가 홍보 시작일 뒤에 연락할 수 있고, 그러면
    # 사전 홍보를 못 한다 (9/21 검토). 기한은 홍보 시작일에서 나온다 — 며칠
    # 전이어야 하는지는 정할 근거가 없어 "홍보 시작 전" 으로만 적는다.
    if first:
        promo_start = _first_date(item.get("홍보_일정") or [])
        steps: list = [
            ("회신", f"홍보 시작({promo_start}) 전까지 연락 주시면 일정이 맞습니다."
                    if promo_start else "관심이 있으시면 연락 주십시오."),
            ("조건 확정", "만나서 매입가·납품 수량·보관을 함께 정합니다."),
        ]
        if promo_start:
            steps.append(("홍보 시작", promo_start))
        if ev.get("기간"):
            steps.append(("판매", ev["기간"]))
        steps.append(("결과 공유", "판매 기간이 끝난 뒤"))
        steps.append(("연락", _contact()))
        out.append({"title": "다음 단계", "items": steps})

    return out


def _first_date(schedule: list) -> str | None:
    """홍보 일정에서 가장 이른 날짜(YYYY-MM-DD). 날짜로 적히지 않은 시점은 건너뛴다."""
    dates = []
    for s in schedule:
        m = re.search(r"\d{4}-\d{2}-\d{2}", str(s.get("시점") or ""))
        if m:
            dates.append(m.group())
    return min(dates) if dates else None


def _contact() -> str:
    """
    연락처 줄. 공개 저장소라 코드에 적지 않고 환경변수 BOTTLING_CONTACT 로 받는다
    (로컬 .env, 배포는 Streamlit Cloud secrets). 없으면 자리표시를 남겨
    빈칸째 나가지 않게 한다.
    """
    contact = os.getenv("BOTTLING_CONTACT")
    return f"바틀링 대표 · {contact}" if contact else "바틀링 대표 (연락처는 보내기 전에 적습니다)"


def _head(meta: dict) -> dict:
    partner = meta.get("partner_name") or "협력사"
    first = (meta.get("round") or 1) == 1
    return {
        "no": f"문서번호: {proposal_no(meta)} | 버전 v1.0 | {'1차 제안' if first else '2차 확정'}",
        "title": "협업 제안서" if first else "협업 확정안",
        "sub": f"공급사: {partner} | 협업 희망일: {meta.get('target_date') or ''}",
        "first": first,
        "partner": partner,
    }


def build_proposal(item: dict, meta: dict) -> str:
    """복사용 텍스트. Word 와 같은 절 목록(_sections)에서 그린다 — 두 벌이 되면 갈라진다."""
    h = _head(meta)
    out: list[str] = [h["no"], h["title"], h["sub"], "", "─" * 52, ""]
    for no, sec in enumerate(_sections(item, meta), 1):
        out += [f"{no}. {sec['title']}", ""]
        pairs = [x for x in sec["items"] if isinstance(x, tuple) and x[0] != "-"]
        w = max((_cols(k) for k, _ in pairs), default=0)
        for x in sec["items"]:
            if isinstance(x, tuple) and x[0] == "-":
                out.append(f"  - {x[1]}")
            elif isinstance(x, tuple):
                out.append(f"  • {_pad(x[0], w)}   {x[1]}")
            else:
                out.append(f"  {x}")
        out.append("")
    if not h["first"]:
        w = max(_cols("바틀링"), _cols(h["partner"]))
        out += ["─" * 52, "", "위 내용에 합의합니다.", "",
                f"{_pad('바틀링', w)}      (서명)                날짜",
                f"{_pad(h['partner'], w)}      (서명)                날짜"]
    return "\n".join(out)


def preview_html(item: dict, meta: dict, sections: int = 3) -> str:
    """
    화면의 종이 모양 미리보기 — 첫 페이지 분량(앞 절 몇 개). 시안(docs/ref/피그마_예시2.pdf).
    Word 와 같은 절 목록에서 그리므로 내려받는 문서와 어긋나지 않는다.
    """
    import html as _h

    h = _head(meta)
    secs = _sections(item, meta)
    parts = [
        f'<div style="font-size:11px;color:#6B7280;margin-bottom:6px">{_h.escape(h["no"])}</div>',
        f'<div style="font-size:22px;font-weight:700;margin-bottom:4px">{_h.escape(h["title"])}</div>',
        f'<div style="font-size:12px;color:#374151;border-bottom:1.5px solid #111827;'
        f'padding-bottom:8px;margin-bottom:14px">{_h.escape(h["sub"])}</div>',
    ]
    for no, sec in enumerate(secs[:sections], 1):
        parts.append(f'<div style="font-size:14px;font-weight:700;margin:14px 0 6px">'
                     f'{no}. {_h.escape(sec["title"])}</div>')
        for x in sec["items"]:
            if isinstance(x, tuple):
                k, v = x
                if k == "-":
                    parts.append(f'<div style="font-size:12px;margin:2px 0 2px 12px">• {_h.escape(str(v))}</div>')
                else:
                    parts.append(
                        '<div style="display:flex;font-size:12px;margin:3px 0 3px 8px">'
                        f'<span style="flex:0 0 110px;color:#374151">• {_h.escape(str(k))}</span>'
                        f'<span style="flex:1">{_h.escape(str(v))}</span></div>')
            else:
                parts.append(f'<div style="font-size:12px;line-height:1.6;margin:4px 0">{_h.escape(str(x))}</div>')
    parts.append(
        '<div style="border-top:1px dashed #D1D5DB;margin-top:24px;padding-top:6px;'
        'display:flex;justify-content:space-between;font-size:10px;color:#9CA3AF">'
        '<span>* 본 미리보기는 1페이지 요약이며 내려받은 문서에 전체 내용이 들어 있습니다.</span>'
        f'<span>Page 1 · 절 {len(secs)}개</span></div>')
    return ('<div style="background:#fff;max-width:640px;margin:0 auto;padding:36px 40px;'
            'box-shadow:0 2px 10px rgba(0,0,0,0.12);border-radius:4px">' + "".join(parts) + "</div>")


def build_proposal_docx(item: dict, meta: dict) -> bytes:
    """
    제안서를 Word 로 만든다. 시안(docs/ref/피그마_예시2.pdf)처럼 문서번호·제목·
    공급사 줄 아래 번호 절, 절 안은 "• 항목   값" 줄이다. 절 목록은 텍스트판과 같다.
    """
    from io import BytesIO

    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt, RGBColor

    h = _head(meta)
    doc = Document()
    for s in doc.sections:
        s.left_margin = s.right_margin = Cm(2.2)
        s.top_margin = s.bottom_margin = Cm(2.0)

    p = doc.add_paragraph()
    r = p.add_run(h["no"])
    r.font.size, r.font.color.rgb = Pt(8), RGBColor(0x6B, 0x72, 0x80)
    p = doc.add_paragraph()
    r = p.add_run(h["title"])
    r.font.size, r.font.bold = Pt(22), True
    p = doc.add_paragraph()
    r = p.add_run(h["sub"])
    r.font.size = Pt(10)
    p.paragraph_format.space_after = Pt(10)

    for no, sec in enumerate(_sections(item, meta), 1):
        hp = doc.add_paragraph()
        hr = hp.add_run(f"{no}. {sec['title']}")
        hr.font.size, hr.font.bold = Pt(12), True
        hp.paragraph_format.space_before = Pt(10)
        hp.paragraph_format.space_after = Pt(4)
        for x in sec["items"]:
            if isinstance(x, tuple) and x[0] == "-":
                doc.add_paragraph(str(x[1]), style="List Bullet")
            elif isinstance(x, tuple):
                # "• 항목 <탭> 값" 한 문단. 값이 두 줄을 넘으면 둘째 줄부터도 값 위치
                # (3.6cm)에서 시작해야 해서 내어쓰기로 잡는다 — 문단 전체를 3.6cm
                # 들이고 첫 줄만 0.4cm 로 당긴다 (9/21 화면 확인).
                pp = doc.add_paragraph()
                pp.paragraph_format.left_indent = Cm(3.6)
                pp.paragraph_format.first_line_indent = Cm(-3.2)
                pp.paragraph_format.space_after = Pt(2)
                k = pp.add_run(f"• {x[0]}")
                k.font.size, k.font.bold = Pt(10), True
                pp.add_run("\t")
                v = pp.add_run(str(x[1]))
                v.font.size = Pt(10)
                pp.paragraph_format.tab_stops.add_tab_stop(Cm(3.6))
            else:
                pp = doc.add_paragraph(str(x))
                pp.paragraph_format.space_after = Pt(4)
                for rr in pp.runs:
                    rr.font.size = Pt(10)

    if not h["first"]:
        doc.add_paragraph()
        doc.add_paragraph("위 내용에 합의합니다.")
        t = doc.add_table(rows=2, cols=3)
        t.style = "Table Grid"
        for row, who in zip(t.rows, ("바틀링", h["partner"])):
            row.cells[0].text, row.cells[1].text, row.cells[2].text = who, "(서명)", "날짜"

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


FONT_DIR = Path(__file__).resolve().parent / "fonts"


def _register_fonts() -> None:
    """나눔고딕(OFL, app/fonts 동봉)을 reportlab 에 등록한다. 여러 번 불러도 된다."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if "Nanum" in pdfmetrics.getRegisteredFontNames():
        return
    pdfmetrics.registerFont(TTFont("Nanum", str(FONT_DIR / "NanumGothic-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Nanum-Bold", str(FONT_DIR / "NanumGothic-Bold.ttf")))
    pdfmetrics.registerFontFamily("Nanum", normal="Nanum", bold="Nanum-Bold",
                                  italic="Nanum", boldItalic="Nanum-Bold")


def build_proposal_pdf(item: dict, meta: dict) -> bytes:
    """
    제안서를 PDF 로 직접 만든다 (reportlab). Word 판과 같은 절 목록·같은 모양이다.

    전에는 Word 파일을 Word 프로그램으로 바꿔 PDF 를 만들어서(docx2pdf) Word 가 있는
    윈도우에서만 됐고 Streamlit Cloud 에서는 미리보기가 HTML 근사판이었다. 이제
    어디서나 같은 PDF 가 나온다 (9/22). Word 파일은 문장을 고칠 때 쓰는 편집용으로 남는다.
    """
    from io import BytesIO
    from xml.sax.saxutils import escape

    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    _register_fonts()
    h = _head(meta)
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm,
                            topMargin=2.0 * cm, bottomMargin=2.0 * cm,
                            title=h["title"], author="바틀링")

    body = ParagraphStyle("body", fontName="Nanum", fontSize=10, leading=15, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor="#6B7280")
    title = ParagraphStyle("title", parent=body, fontName="Nanum-Bold", fontSize=22, leading=28,
                           spaceBefore=4, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=body, fontName="Nanum-Bold", fontSize=12, leading=16,
                        spaceBefore=10, spaceAfter=4)
    label = ParagraphStyle("label", parent=body, fontName="Nanum-Bold")
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=0.9 * cm, bulletIndent=0.4 * cm)

    flow = [Paragraph(escape(h["no"]), small), Paragraph(escape(h["title"]), title),
            Paragraph(escape(h["sub"]), body), Spacer(1, 10)]

    for no, sec in enumerate(_sections(item, meta), 1):
        flow.append(Paragraph(escape(f"{no}. {sec['title']}"), h2))
        rows = []           # 이어지는 「항목 | 값」 줄은 표 하나로 묶는다 — 값이 길면 줄바꿈이
                            # 값 칸 안에서만 일어나 Word 의 내어쓰기와 같은 모양이 된다

        def flush():
            if rows:
                t = Table(rows, colWidths=[3.2 * cm, None], hAlign="LEFT")
                t.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]))
                flow.append(t)
                rows.clear()

        for x in sec["items"]:
            if isinstance(x, tuple) and x[0] == "-":
                flush()
                flow.append(Paragraph(escape(str(x[1])), bullet, bulletText="•"))
            elif isinstance(x, tuple):
                rows.append([Paragraph(escape(f"• {x[0]}"), label),
                             Paragraph(escape(str(x[1])), body)])
            else:
                flush()
                flow.append(Paragraph(escape(str(x)), body))
        flush()

    if not h["first"]:
        flow += [Spacer(1, 12), Paragraph("위 내용에 합의합니다.", body)]
        sign = Table([[who, "(서명)", "날짜"] for who in ("바틀링", h["partner"])],
                     colWidths=[4 * cm, 5 * cm, 4 * cm])
        sign.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, "#111827"),
                                  ("FONTNAME", (0, 0), (-1, -1), "Nanum")]))
        flow.append(sign)

    doc.build(flow)
    return buf.getvalue()


def docx_to_pdf(docx_bytes: bytes) -> bytes | None:
    """
    docx 를 PDF 로 바꾼다. 미리보기와 PDF 내려받기가 이것을 쓴다.

    [임시 경로] Word 가 있는 윈도우에서만 된다 — docx2pdf 가 Word 를 불러 바꾼다
      (requirements-windows.txt). Streamlit Cloud 에는 Word 가 없어 항상 None 이다.
      배포 전에 reportlab 으로 PDF 를 직접 만드는 것으로 바꾼다 — 그러면 어디서나
      같은 문서가 나온다 (남은 작업표). 없거나 실패하면 None, 화면은 HTML 근사로.
    """
    import tempfile
    from pathlib import Path

    try:
        from docx2pdf import convert
    except ImportError:
        return None
    try:
        # PDF 는 바이트로 읽고 나서 임시 폴더를 닫는다. 파일을 열어 둔 채 폴더를
        # 지우면 윈도우가 "다른 프로세스가 사용 중" 이라며 막는다.
        with tempfile.TemporaryDirectory() as d:
            src, pdf = Path(d) / "proposal.docx", Path(d) / "proposal.pdf"
            src.write_bytes(docx_bytes)
            convert(str(src), str(pdf))
            return pdf.read_bytes()
    except Exception:
        return None


def pdf_pages(pdf_bytes: bytes, dpi: int = 110) -> list[bytes]:
    """PDF 의 페이지들을 PNG 로 그린다. 화면 미리보기가 ‹ › 로 넘겨 본다."""
    import pymupdf

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    zoom = dpi / 72
    pages = [p.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png") for p in doc]
    doc.close()
    return pages


# 제안서를 만들려면 그 안에 있어야 하는 것 (명세서 5-1 A10)
REQUIRED = ("역할분담", "상호_이익", "배경", "매입")


def missing_fields(item: dict) -> list[str]:
    """비어 있는 필수 항목. 비어 있으면 문서를 만들지 않는다."""
    return [k for k in REQUIRED if not item.get(k)]
