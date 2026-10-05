"""
Gemini 호출 래퍼. JSON 강제 출력.

[SDK] google-genai (2026-08-24 교체)
  구 SDK(google-generativeai)는 thinking 옵션을 지원하지 않으며 지원 종료 예정이다.
  상세는 명세서 6-2-3 참조.

[모델] gemini-3.5-flash-lite
  상위 모델(3.6-flash) 대비 7배 빠르며 품질 검사를 모두 통과했다.
  4단계 체인 실측 약 17초.

[thinking] 사용하지 않는다
  lite 계열은 원래 추론을 거의 하지 않아 조절 여지가 없다.
  budget=128 적용 시 시간 이득 없이 편차만 0.7 → 2.3초로 증가했다.
"""
import json
import time

from google import genai
from google.genai import types

from config.settings import (GEMINI_API_KEY, GEMINI_API_KEY_PAID,
                             GEMINI_MODEL)

_client: genai.Client | None = None
_client_paid: genai.Client | None = None

# 호출마다 토큰을 누적한다. 기획안 1건에 재호출·되감기까지 몇 번을 부르고
# 얼마가 드는지 재는 용도다. 호출자(runner)의 반환 형식은 그대로 두고,
# 재고 싶은 쪽이 전후로 읽는다 (tests/test_fixed.py).
USAGE = {"calls": 0, "input_tokens": 0, "output_tokens": 0}


def reset_usage() -> None:
    USAGE.update(calls=0, input_tokens=0, output_tokens=0)


def get_client(paid: bool = False) -> genai.Client:
    """
    제미나이를 부를 때 쓰는 객체. paid 를 주면 유료 키로 진행한다.

    지금은 부르는 곳이 모두 유료 키를 쓴다.

      메뉴 수집     가게 하나에 30번을 부른다. 무료 키는 분당 한도에 걸려
                   호출마다 20~40초씩 쉬고, 한도가 차면 한 가게에 10분이 넘는다
      기획안 네 단계  무료 키는 하루 한도가 있어 몇 건 만들면 더 못 만든다.
                   한도는 태평양 자정(한국 16시)에 풀린다. 그리고 협력사
                   매입가가 들어가는 쪽이라, 보낸 내용이 학습에 쓰이지 않는
                   유료 키로 보내는 것이 맞다 — 대표님께도 그렇게 안내했다
    """
    global _client, _client_paid
    if paid:
        if _client_paid is None:
            if not GEMINI_API_KEY_PAID:
                raise RuntimeError("환경변수 GEMINI_API_KEY_PAID 가 없습니다.")
            _client_paid = genai.Client(api_key=GEMINI_API_KEY_PAID)
        return _client_paid
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("환경변수 GEMINI_API_KEY 가 없습니다.")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def call(prompt: str, retry: int = 2, model: str | None = None,
         on_wait=None, temperature: float | None = None,
         paid: bool = False) -> tuple[dict, int]:
    """
    JSON 응답을 강제하고 파싱해서 돌려준다.

    반환: (파싱된 dict, 소요 ms)

    paid 를 주면 유료 키로 부른다 (get_client 설명 참고).

    temperature 를 주면 그 값으로 부른다. 안 주면 모델 기본값이다.
      글에 적힌 사실을 그대로 뽑아 오는 일에는 0 을 준다. 기본값으로 두면
      같은 글에서 뽑은 결과가 호출마다 달라진다 — 블로그 후기에서 메뉴를
      뽑을 때 5개가 나왔다 1개가 나왔다 했다 (10/5).
      기획안을 만드는 네 단계는 글을 짓는 일이라 기본값을 그대로 쓴다.

    retry 는 JSON 파싱 실패와 일시적 오류에만 적용된다.
    429(할당량 초과)는 대기 후 재시도한다.

    on_wait(초, 시도횟수): 429 대기에 들어갈 때 부른다.
      대기가 20초부터 시작하는데 그동안 화면에는 직전 단계 문구가 그대로
      떠 있어, 멈춘 것처럼 보인다. 호출자가 그 사실을 표시할 수 있게 알린다.

    [주의] 여기의 retry 는 전송 계층 재시도다. 같은 프롬프트를 그대로 다시
      보내므로 파싱 실패·429 는 넘겨도 내용 오류는 못 잡는다. 생성물이
      제약을 어긴 경우의 재호출은 runner 의 되감기가 맡는다. 층위가 다르다.
    """
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json",
        **({"temperature": temperature} if temperature is not None else {}))
    model_name = model or GEMINI_MODEL
    last_err = None

    for attempt in range(retry + 1):
        t0 = time.perf_counter()
        try:
            resp = get_client(paid).models.generate_content(
                model=model_name, contents=prompt, config=cfg
            )
            ms = int((time.perf_counter() - t0) * 1000)
            um = getattr(resp, "usage_metadata", None)
            USAGE["calls"] += 1
            USAGE["input_tokens"] += getattr(um, "prompt_token_count", 0) or 0
            USAGE["output_tokens"] += getattr(um, "candidates_token_count", 0) or 0
            return json.loads(resp.text), ms

        except json.JSONDecodeError as e:
            last_err = e
            print(f"[retry {attempt}] JSON 파싱 실패: {e}")
            # 어디가 깨졌는지 보이게 오류 지점 앞뒤를 찍는다 (9/21 C6 에서 반복)
            print("    …" + resp.text[max(0, e.pos - 120):e.pos + 60].replace("\n", "⏎") + "…")

        except Exception as e:
            last_err = e
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                wait = 20 * (attempt + 1)
                print(f"[retry {attempt}] 호출 한도 도달 — {wait}초 대기")
                if on_wait:
                    on_wait(wait, attempt)
                time.sleep(wait)
            else:
                print(f"[retry {attempt}] 호출 실패: {msg[:100]}")

    raise RuntimeError(f"Gemini 호출 실패: {last_err}")
