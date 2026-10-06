"""
제미나이를 얼마나 불렀고 얼마가 나갔는지 `api_usage` 에 남긴다.

[왜 남기나]

유료 키는 대표님 계정으로 발급된 것이고 청구도 대표님께 간다. 우리 쪽에서
얼마가 쓰였는지 볼 수 없으면 나중에 설명할 수가 없다. 그래서 부른 쪽에서
직접 남긴다.

[기능과 키는 따로 본다]

「메뉴 수집이니까 무료」처럼 **기능으로 키를 짐작하지 않는다.** 메뉴 수집은
지금 무료 키를 쓰지만, 분당 한도에 여러 번 걸리면 유료로 넘기는 것을 검토
중이다. 그러면 한 번 수집하는 동안 무료와 유료가 섞인다.

그래서 호출 하나하나가 실제로 쓴 키를 들고 오고(`chain.gemini.USAGE`), 여기서는
**키 종류마다 한 줄씩** 남긴다. 섞인 수집은 두 줄이 된다.

  기능        키    호출  금액
  메뉴 수집    무료   22    0원      ← 한도에 걸리기 전까지
  메뉴 수집    유료    8   18원      ← 넘어간 뒤

[무료는 금액이 0 이다]

무료 호출은 돈이 나가지 않으므로 금액을 0 으로 남긴다. 호출 수와 토큰은 무료든
유료든 다 남긴다 — 「얼마나 썼나」와 「얼마가 나갔나」는 다른 질문이고, 무료
한도를 얼마나 당겨썼는지도 봐야 한다.

[환율을 함께 남긴다]

원화 금액만 남기면 환율이 바뀔 때 지난 기록을 설명할 수 없다. 그때 쓴 환율을
같은 줄에 적어 둔다. 설정값을 바꿔도 지난 줄은 그대로다.

[실패해도 흐름을 멈추지 않는다]

기록이 안 돼도 기획안과 수집은 그대로 끝나야 한다 (작업 원칙 ⑤). 넣기가
실패하면 콘솔에만 적고 넘어간다.
"""
from chain.gemini import USAGE, reset_usage
from config.settings import (GEMINI_MODEL, GEMINI_USD_PER_M_INPUT,
                             GEMINI_USD_PER_M_OUTPUT, KRW_PER_USD)
from db.client import get_client

TABLE = "api_usage"

# 기능 이름. 화면에 그대로 나가는 말이라 여기서 한 번만 정한다.
PLAN = "기획안 생성"
COLLECT = "메뉴 수집"

# USAGE 의 칸 이름 → 기록에 적을 키 종류
KEYS = (("paid", "유료"), ("free", "무료"))


def start() -> None:
    """재기 시작. 부르는 쪽이 일을 시작할 때 한 번 부른다."""
    reset_usage()


def money(input_tokens: int, output_tokens: int, paid: bool) -> tuple[float, int]:
    """
    (달러, 원). **유료 호출만 금액을 매긴다.** 무료는 0 이다.

    무료 키로 보낸 것은 돈이 나가지 않는다. 토큰은 그대로 남기고 금액만 0 으로
    둔다 — 나중에 메뉴 수집을 유료로 돌리면 이 함수를 고치지 않아도 금액이
    붙기 시작한다.
    """
    if not paid:
        return 0.0, 0
    usd = (input_tokens / 1_000_000 * GEMINI_USD_PER_M_INPUT
           + output_tokens / 1_000_000 * GEMINI_USD_PER_M_OUTPUT)
    return round(usd, 6), round(usd * KRW_PER_USD)


def rows(kind: str, partner_id: int | None = None,
         partner_name: str | None = None, note: str | None = None) -> list[dict]:
    """
    지금까지 쌓인 사용량을 넣을 줄로 바꾼다. 쓴 키마다 한 줄이다.

    한 번도 안 부른 키는 줄을 만들지 않는다. 빈 줄이 쌓이면 화면에서 세기가
    어려워진다.
    """
    out = []
    for slot, label in KEYS:
        used = USAGE.get(slot) or {}
        if not used.get("calls"):
            continue
        usd, krw = money(used["input_tokens"], used["output_tokens"],
                         paid=(slot == "paid"))
        out.append({
            "kind": kind,
            "key_kind": label,
            "partner_id": partner_id,
            "partner_name": partner_name,
            "model": GEMINI_MODEL,
            "calls": used["calls"],
            "input_tokens": used["input_tokens"],
            "output_tokens": used["output_tokens"],
            "usd": usd,
            "krw": krw,
            "krw_per_usd": KRW_PER_USD,
            "note": note,
        })
    return out


def record(kind: str, partner_id: int | None = None,
           partner_name: str | None = None, note: str | None = None) -> list[dict]:
    """
    사용량을 남긴다. 넣은 줄을 돌려준다.

    실패해도 예외를 올리지 않는다 (작업 원칙 ⑤). 부르는 쪽은 돌려받은 줄이
    비었는지로만 알 수 있고, 그것으로 흐름을 바꾸지는 않는다.
    """
    try:
        made = rows(kind, partner_id, partner_name, note)
        if made:
            get_client().table(TABLE).insert(made).execute()
        return made
    except Exception as e:
        print(f"[사용량 기록 실패] {kind}: {type(e).__name__}: {e}")
        return []
