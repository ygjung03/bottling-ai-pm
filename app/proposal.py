"""
협업 제안서 생성 — 협력사에 그대로 보내는 문서 (T44, 명세서 1-4)

[담당] B

화면에서 떼어 둔 이유는 이 문서가 밖으로 나가기 때문이다. Streamlit 을
띄우지 않고 검증할 수 있어야 `tests/test_proposal.py` 가 실제 체인 출력으로
문서를 만들어 볼 수 있다. 화면(`app/pages/2_기획안_생성.py`)은 여기서 만든
것을 그리기만 한다.

[새로 만드는 내용이 없다]
  (4) 컨설턴트가 1위 안에 채운 역할분담·상호_이익·배경·매입을 옮겨 담을
  뿐이다. 여기서 문장을 지어내면 화면에 보이는 것과 협력사가 받는 것이
  달라진다.
"""
import re
import unicodedata
from datetime import datetime, timedelta, timezone

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
    "매입가 1,500원", "1500원 — 판매가 4000원 대비 38%" 에서 앞의 금액을 뽑는다.

    "산출 불가" 나 숫자가 없는 문장이면 None. 모르는 값을 0 으로 두면
    마진이 판매가 전액으로 잡혀 실제보다 좋아 보인다.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    m = re.search(r"(\d[\d,]*)", str(text))
    return int(m.group(1).replace(",", "")) if m else None


def proposal_no(meta: dict) -> str:
    """
    문서번호. 협력사가 받는 문서라 어느 건인지 가리킬 수 있어야 한다.

    plans.id 를 쓴다. 저장에 실패했으면 번호를 지어내지 않고 초안으로 표시한다.
    번호가 있는데 DB 에 없는 문서가 돌아다니면 나중에 대조가 안 된다.
    """
    pid = meta.get("plan_id")
    year = datetime.now(KST).year
    return f"BTL-{year}-{pid:04d}" if pid else f"BTL-{year}-초안"


def build_proposal(item: dict, meta: dict) -> str:
    """
    협력사에 보낼 제안서 본문.

    [배치는 시안을 따랐다] docs/ref/figma_최종기획안.png
      문서번호·작성일·버전을 머리에 두고, 절에 번호를 붙이고, 끝에 서명란을 둔다.
      협력사가 검토하고 확정하는 문서라는 성격이 드러난다.

    [시안의 수익 배분은 쓰지 않는다]
      시안은 세 상점이 세트를 만들어 수익을 나누는 구조다. 우리는 바틀링이
      협력사 완제품을 매입해 파는 구조라(기획서 6-1) 나눌 비율이 없고
      매입가 하나가 협의 대상이다.
    """
    deal = item.get("매입") or {}
    basis = deal.get("근거") if isinstance(deal.get("근거"), dict) else {}
    roles = item.get("역할분담") or {}
    gains = item.get("상호_이익") or {}
    ev = item.get("이벤트") or {}
    price = item.get("판매가_제안")

    def pairs(rows: list[tuple[str, str]]) -> list[str]:
        w = max((_cols(k) for k, _ in rows), default=0)
        return [f"{_pad(k, w)}   {v}" for k, v in rows]

    # 절 번호는 마지막에 붙인다. 번호를 제목에 박아 두면 배경이나 협의
    # 사항처럼 있을 때만 넣는 절 때문에 번호가 튄다.
    sections: list[tuple[str, list[str]]] = []

    sections.append(("제안 개요", pairs([
        ("제안 대상", meta.get("partner_name") or "협력사"),
        ("제안 주체", "바틀링 (서울 광진구 뚝섬로34길 67)"),
        ("협업 메뉴", item.get("메뉴명") or ""),
        ("구성", item.get("구성") or ""),
        ("실행 예정일", meta.get("target_date") or ""),
        ("협업 방식", "완제품 매입 후 판매"),
    ])))

    if item.get("배경"):
        sections.append(("제안 배경", [item["배경"]]))

    # 한 쪽이 여러 줄이면 두 번째 줄부터는 이름 자리를 비운다.
    # 같은 이름을 반복해 적으면 몇 가지를 맡는지가 눈에 안 들어온다.
    role_lines = []
    role_w = max(_cols("바틀링"), _cols("협력사"))
    for side in ("바틀링", "협력사"):
        for i, x in enumerate(roles.get(side) or []):
            role_lines.append(f"{_pad(side if i == 0 else '', role_w)}   {x}")
    sections.append(("역할분담", role_lines or ["데이터 없음"]))

    # 협력사가 사전 홍보를 맡는데 언제 올릴지가 문서에 없으면 실행 전에
    # 올라가지 않는다. 지난 협업 셋이 모두 홍보에서 아쉬웠던 지점이다 (1-5).
    promo = [(str(s.get("시점")), str(s.get("채널") or ""), str(s.get("내용") or ""))
             for s in (item.get("홍보_일정") or []) if s.get("시점")]
    if promo:
        w_when = max(_cols(w) for w, _, _ in promo)
        w_ch = max(_cols(c) for _, c, _ in promo)
        sections.append(("홍보 일정", [
            f"{_pad(when, w_when)}   {_pad(ch, w_ch)}   {what}".rstrip()
            for when, ch, what in promo
        ]))

    sections.append(("서로 얻는 것", pairs([
        ("바틀링", gains.get("바틀링") or "데이터 없음"),
        ("협력사", gains.get("협력사") or "데이터 없음"),
    ])))

    cond = [("협업 방식", "완제품 매입 후 판매")]
    if deal.get("제안_매입가"):
        # (4)가 "1,200원 — 판매가 4000원 대비 30%" 처럼 판매가를 함께 적는다.
        # 바로 아래 줄에 판매가가 또 나오므로 금액만 남긴다.
        amount = won(deal["제안_매입가"])
        shown = f"{amount:,}원" if amount else str(deal["제안_매입가"])
        note = "  ※ 협의 필요" if deal.get("협의_필요") else ""
        cond.append(("제안 매입가", f"{shown}{note}"))
    if price:
        cond.append(("판매가", f"{price:,}원"))
    if deal.get("협력사_수익"):
        cond.append(("협력사 수익", deal["협력사_수익"]))
    cond += [("보관 조건", item.get("보관_조건") or "협의 필요"),
             ("1회 납품 수량", item.get("1회_납품_수량") or "협의 필요"),
             ("실행 기간", ev.get("기간") or "협의 필요")]
    sections.append(("조건", pairs(cond)))

    # 모르는 것을 모른다고 적는다. 협력사가 무엇을 정해 와야 하는지가 보인다
    todo = list(basis.get("미확인") or [])
    if deal.get("협의_필요"):
        todo.append("매입가 최종 확정")

    # 조건 절에 「협의 필요」로 남은 값은 여기에도 올린다. 표 안에만 있으면
    # 협력사가 무엇을 정해 와야 하는지 한눈에 보이지 않는다.
    for label, key in [("1회 납품 수량", "1회_납품_수량"),
                       ("보관 조건", "보관_조건")]:
        if "협의" in str(item.get(key) or ""):
            todo.append(label)
    if todo:
        sections.append(("협의가 필요한 사항", [f"- {x}" for x in todo]))

    out: list[str] = [
        "협업 제안서", "",
        *pairs([("문서번호", proposal_no(meta)),
                ("작성일", datetime.now(KST).strftime("%Y.%m.%d")),
                ("버전", "v1.0")]),
        "", "─" * 52, "",
    ]
    for no, (title, lines) in enumerate(sections, 1):
        out += [f"{no}. {title}", ""] + [f"  {x}" for x in lines] + [""]

    # 서명란. 상호 길이가 달라도 (서명)·날짜가 세로로 맞도록 폭을 맞춘다
    partner = meta.get("partner_name") or "협력사"
    w = max(_cols("바틀링"), _cols(partner))
    out += ["─" * 52, "",
            "위 내용에 합의합니다.", "",
            f"{_pad('바틀링', w)}      (서명)                날짜",
            f"{_pad(partner, w)}      (서명)                날짜"]
    return "\n".join(out)


def build_proposal_docx(text: str, meta: dict) -> bytes:
    """
    제안서를 Word 로 만든다.

    실물 제안서가 .docx 로 오갔으므로 같은 형식을 맞춘다.
    본문은 복사용 텍스트와 같은 것을 쓴다 — 두 벌이 되면 갈라진다.
    """
    from io import BytesIO

    from docx import Document
    from docx.shared import Pt

    doc = Document()
    doc.add_heading("협업 제안서", level=0)

    head = doc.add_paragraph()
    head.add_run(f"문서번호 {proposal_no(meta)}   |   "
                 f"작성일 {datetime.now(KST).strftime('%Y.%m.%d')}   |   버전 v1.0")
    head.runs[0].font.size = Pt(9)

    # 복사용 텍스트의 절 구분을 그대로 따라간다
    for line in text.splitlines():
        s = line.strip()
        if not s or set(s) == {"─"}:
            continue
        if s == "협업 제안서" or s.startswith(("문서번호", "작성일", "버전")):
            continue
        if re.match(r"^\d\. ", s):
            doc.add_heading(s, level=1)
        else:
            p = doc.add_paragraph(s)
            p.paragraph_format.space_after = Pt(2)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


# 제안서를 만들려면 1위 안에 있어야 하는 것 (명세서 5-1 A10)
REQUIRED = ("역할분담", "상호_이익", "배경", "매입")


def missing_fields(item: dict) -> list[str]:
    """비어 있는 필수 항목. 비어 있으면 문서를 만들지 않는다."""
    return [k for k in REQUIRED if not item.get(k)]
