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
from datetime import date, datetime, timedelta, timezone

from chain.gemini import USAGE, reset_usage
from config.settings import (GEMINI_MODEL, GEMINI_PREPAID_USD,
                             GEMINI_SPENT_BEFORE_KRW,
                             GEMINI_SPENT_BEFORE_MONTH,
                             GEMINI_USD_PER_M_INPUT,
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


# ══════════════════════════════════════════
# 집계 — 관리 화면의 사용량 탭이 쓴다
# ══════════════════════════════════════════
#
# 화면이 아니라 여기 둔다. 숫자가 맞는지는 화면을 띄우지 않고도 확인할 수 있어야
# 한다.
#
# **created_at 은 UTC 다.** 「오늘」과 「이번 달」을 UTC 로 자르면 한국 새벽에
# 쓴 것이 전날로 넘어간다. 읽자마자 한국 시간으로 바꿔 둔다.

KST = timezone(timedelta(hours=9))


def fetch(limit: int = 2000) -> list[dict]:
    """사용량 기록. 시각을 한국 시간으로 바꿔 「때」 칸에 함께 담는다."""
    try:
        rows_ = (get_client().table(TABLE).select("*")
                 .order("created_at", desc=True).limit(limit).execute().data or [])
    except Exception as e:
        print(f"[사용량 조회 실패] {type(e).__name__}: {e}")
        return []
    for r in rows_:
        r["때"] = datetime.fromisoformat(r["created_at"]).astimezone(KST)
    return rows_


def summarize(rows_: list[dict], today: date | None = None) -> dict:
    """
    사용량 탭에 올릴 값들.

      쓴_금액      기록 이전 금액 + 기록된 유료 금액. 선불 잔액을 견주는 값이다
      기록_금액    기록된 유료 금액만
      이번달       한국 날짜로 자른다. **기록 이전 금액을 쓴 달이면 그것까지 더한다**
      오늘         기록된 것만. 한국 날짜로 자른다
      종류별       {종류: {건수, 호출, 금액, 평균}}. **평균은 유료 줄만으로 낸다**
      날짜별       [(날짜, 금액)] 최근 것부터. 무료만 쓴 날도 0원으로 들어간다
      최근         최근 10건

    **평균을 무료와 섞지 않는다.** 무료는 금액이 0 이라 함께 평균을 내면 값이
    희석된다 — 유료 6건 210원인데 무료 17건을 섞으면 9원이 된다.
    """
    today = today or datetime.now(KST).date()
    paid = [r for r in rows_ if r.get("key_kind") == "유료"]
    logged = sum(r.get("krw") or 0 for r in paid)

    by_kind: dict[str, dict] = {}
    for r in rows_:
        k = by_kind.setdefault(r["kind"], {"건수": 0, "호출": 0, "금액": 0,
                                           "유료건수": 0})
        k["건수"] += 1
        k["호출"] += r.get("calls") or 0
        k["금액"] += r.get("krw") or 0
        if r.get("key_kind") == "유료":
            k["유료건수"] += 1
    for k in by_kind.values():
        k["평균"] = round(k["금액"] / k["유료건수"]) if k["유료건수"] else 0

    # 날짜는 유료·무료를 가리지 않고 센다. 무료만 쓴 날이 빠지면 「쓴 날」과
    # 「돈이 나간 날」이 같은 것처럼 보인다 — 무료로 몇 번을 돌렸는지도 봐야 한다.
    by_day: dict[date, int] = {}
    for r in rows_:
        d = r["때"].date()
        by_day[d] = by_day.get(d, 0) + (r.get("krw") or 0)

    # 기록 이전 금액을 쓴 달에는 그 금액도 「이번 달」에 든다. 빼면 10월에
    # 210원 쓴 것으로 보인다 — 실제로는 1,221원이다. 다음 달부터는 달이 달라
    # 저절로 0 이 되고, 그때는 쓴 것이 전부 기록에 남는다.
    이전달치 = (GEMINI_SPENT_BEFORE_KRW
             if f"{today:%Y-%m}" == GEMINI_SPENT_BEFORE_MONTH else 0)

    return {
        "쓴_금액": GEMINI_SPENT_BEFORE_KRW + logged,
        "기록_금액": logged,
        "이전_금액": GEMINI_SPENT_BEFORE_KRW,
        "충전_금액": round(GEMINI_PREPAID_USD * KRW_PER_USD),
        "이번달": 이전달치 + sum(r.get("krw") or 0 for r in paid
                          if (r["때"].year, r["때"].month) == (today.year, today.month)),
        "오늘": sum(r.get("krw") or 0 for r in paid if r["때"].date() == today),
        "종류별": by_kind,
        "날짜별": sorted(by_day.items(), reverse=True),
        "최근": rows_[:10],
    }
