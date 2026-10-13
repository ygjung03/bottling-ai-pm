"""
추천받기 에이전트 — 기간을 받아 「언제 · 누구와 · 무엇을」 1~5위로 제안.

    기간(캘린더) → 그 기간의 행사 + 점수 상위 가게 + 맥주 라인업
                → 제미나이 1회 → 날짜 · 가게 · 메뉴 아이디어 · 이유 3줄

[점수는 그대로 사용]
  가게를 고르는 기준 => nearby_stores.score. AI 는 점수 상위 후보 안에서 기간·행사에 맞춰 고르고 설명을 한다.

[DB를 기반으로 찾을 것]
  후보를 S1, S2… 번호로 넘기고 번호로만 받기. 번호가 후보에 없으면 제외.

[무료 키 · 1회]
  공개 정보(행사 · 가게 이름 · 업종 · 맥주 라인업)만 넘기므로 무료 키로 호출.
  분당 15회 한도라 추천 한 번에 한 번만 호출.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from chain.gemini import call
from db.client import get_client

# 배포는 UTC 라 그냥 today() 를 쓰면 새벽에 캘린더 기본값이 어제로 뜬다.
KST = timezone(timedelta(hours=9))

MAX_PICKS = 5
MAX_CANDIDATES = 30     # 점수 상위 몇 곳까지 AI 에게 보여줄지
MAX_EVENTS = 25

PROMPT = """너는 서울 광진구 자양동 크래프트 맥주 펍 「바틀링」(뚝섬한강공원 앞, 셀프탭)의 협업 기획자다.
대표님이 협업할 수 있는 기간을 골랐다. 그 기간 안에서 「언제 · 어느 가게와 · 어떤 메뉴로」
협업하면 좋을지 1~{n}위로 제안하라.

[협업 가능 기간] {start} ~ {end}

[그 기간의 근처 행사] (기간이 짧은 순)
{events}

[협업 후보 가게] (번호 / 상호 / 업종 / 바틀링까지 거리 / 추천 점수 — 점수는 거리·업종 궁합으로 미리 매긴 값)
{stores}

[바틀링 맥주 라인업]
{beers}

[규칙]
1. 가게는 위 후보 번호(S1, S2…)로만 고른다. 목록에 없는 가게를 만들지 마라. 같은 가게를 두 번 고르지 마라.
2. 날짜는 협업 가능 기간 안의 하루(YYYY-MM-DD)다. 행사가 있으면 행사 당일이나 직전 주말처럼
   손님이 몰리는 날을 고르고, 그 행사 이름을 event 에 적는다. 연계할 행사가 없으면 event 는 "없음".
3. 점수가 높은 가게를 우선하되, 행사 성격에 더 맞는 가게가 있으면 순위를 바꿔도 된다 — 이유에 밝혀라.
4. menu 는 그 가게 업종으로 낼 수 있는 협업 메뉴 아이디어 하나다 (예: "크리스피 치킨 + 라거 세트").
   가게의 실제 메뉴는 모르므로 업종에서 흔한 메뉴로 적고, 맥주는 라인업에 있는 것만 쓴다. 논알콜은 페어링에서 뺀다.
5. reasons 는 정확히 3줄. ① 왜 이 날짜인가 ② 왜 이 가게인가 ③ 왜 이 메뉴인가. 각 줄 한 문장.
6. 행사 데이터에 없는 사실(방문객 수, 가게 메뉴, 가격)을 지어내지 마라.
7. reasons 와 menu 에 후보 번호(S1, S2…)를 쓰지 마라. 가게는 상호로 부른다. 날짜의 요일을 틀리지 마라.

[출력] JSON 하나.
{{"picks": [{{"rank": 1, "store": "S번호", "date": "YYYY-MM-DD", "event": "행사 이름 또는 없음",
              "menu": "협업 메뉴 아이디어", "reasons": ["...", "...", "..."]}}]}}
"""


def load_events(start: date, end: date) -> list[dict]:
    """기간과 겹치는 행사. 짧은 행사가 날짜를 고를 근거가 되므로 기간이 짧은 순으로."""
    rows = (get_client().table("events")
            .select("title,place,start_date,end_date,distance_m,source")
            .lte("start_date", end.isoformat())
            .gte("end_date", start.isoformat())
            .limit(200).execute().data or [])

    def length(e):
        s = date.fromisoformat(e["start_date"])
        t = date.fromisoformat(e.get("end_date") or e["start_date"])
        return (t - s).days

    seen, out = set(), []
    for e in sorted(rows, key=length):
        key = (e.get("title") or "").strip()
        if key and key not in seen:          # 같은 이름의 행사는 한 번만
            seen.add(key)
            out.append(e)
    return out[:MAX_EVENTS]


def _event_lines(events: list[dict]) -> str:
    if not events:
        return "- (이 기간에 수집된 행사 없음)"
    lines = []
    for e in events:
        span = e["start_date"] if e["start_date"] == e.get("end_date") \
            else f"{e['start_date']} ~ {e.get('end_date')}"
        place = f" / {e['place']}" if e.get("place") else ""
        dist = f" / 약 {e['distance_m']}m" if e.get("distance_m") else ""
        lines.append(f"- {e.get('title')} / {span}{place}{dist}")
    return "\n".join(lines)


def _store_lines(cands: list[dict]) -> tuple[str, dict[str, dict]]:
    by_no, lines = {}, []
    for i, c in enumerate(cands[:MAX_CANDIDATES], 1):
        no = f"S{i}"
        by_no[no] = c
        lines.append(f"- {no} / {c['name']} / {c.get('tier') or '업종 미상'} / "
                     f"{int(c['distance_m'])}m / {float(c['score']):.2f}")
    return "\n".join(lines), by_no


def build_prompt(start: date, end: date, cands: list[dict], events: list[dict],
                 beers: str) -> tuple[str, dict[str, dict]]:
    stores, by_no = _store_lines(cands)
    prompt = PROMPT.format(n=MAX_PICKS, start=start.isoformat(), end=end.isoformat(),
                           events=_event_lines(events), stores=stores,
                           beers=beers or "- (라인업 데이터 없음)")
    return prompt, by_no


def _drop_no(text: str) -> str:
    """「S1 델리하우스」처럼 이유에 섞여 나온 후보 번호를 뗀다 (10/14 첫 실행에서 나옴)."""
    return re.sub(r"\bS\d{1,2}\s*", "", text).strip()


def check_picks(raw: dict, by_no: dict[str, dict], start: date, end: date) -> list[dict]:
    """
    AI 응답을 검사해 쓸 수 있는 것만 남긴다.

      - 후보에 없는 번호 → 버림 (지어낸 가게)
      - 같은 가게 두 번 → 뒤엣것 버림
      - 날짜가 기간 밖이거나 형식이 틀림 → 버림
      - 이유가 3줄이 아니면 있는 만큼만 (빈 줄은 뺀다)
    """
    picks = raw.get("picks", []) if isinstance(raw, dict) else []
    out, used = [], set()
    for p in picks:
        if not isinstance(p, dict):
            continue
        store = by_no.get(str(p.get("store", "")).strip().upper())
        if not store or store["store_id"] in used:
            continue
        try:
            d = date.fromisoformat(str(p.get("date", "")).strip())
        except ValueError:
            continue
        if not (start <= d <= end):
            continue
        reasons = [_drop_no(str(r)) for r in (p.get("reasons") or []) if str(r).strip()][:3]
        event = str(p.get("event") or "").strip()
        used.add(store["store_id"])
        out.append({
            "store": store,
            "date": d,
            "event": None if event in ("", "없음") else event,
            "menu": _drop_no(str(p.get("menu") or "")),
            "reasons": reasons,
        })
        if len(out) == MAX_PICKS:
            break
    for i, p in enumerate(out, 1):           # AI 가 준 rank 대신 남은 순서로 다시 매긴다
        p["rank"] = i
    return out


def recommend(start: date, end: date, cands: list[dict], beers: str,
              on_wait=None) -> tuple[list[dict], list[dict]]:
    """
    반환: (추천 목록, AI 에 보여준 행사 목록)

    추천이 비면 호출자가 「다시 시도」를 띄운다. 예외는 그대로 올린다 — 화면이 알린다.
    """
    events = load_events(start, end)
    prompt, by_no = build_prompt(start, end, cands, events, beers)
    raw, _ms = call(prompt, on_wait=on_wait)      # 무료 키 (paid 를 주지 않는다)
    return check_picks(raw, by_no, start, end), events


def default_range(today: date | None = None) -> tuple[date, date]:
    """캘린더 처음 값 — 오늘부터 2주."""
    today = today or datetime.now(KST).date()
    return today, today + timedelta(days=14)