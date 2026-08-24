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

from config.settings import GEMINI_API_KEY, GEMINI_MODEL

_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("환경변수 GEMINI_API_KEY 가 없습니다.")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def call(prompt: str, retry: int = 1, model: str | None = None) -> tuple[dict, int]:
    """
    JSON 응답을 강제하고 파싱해서 돌려준다.

    반환: (파싱된 dict, 소요 ms)

    retry 는 JSON 파싱 실패와 일시적 오류에만 적용된다.
    429(할당량 초과)는 대기 후 재시도한다.
    """
    cfg = types.GenerateContentConfig(response_mime_type="application/json")
    model_name = model or GEMINI_MODEL
    last_err = None

    for attempt in range(retry + 1):
        t0 = time.perf_counter()
        try:
            resp = get_client().models.generate_content(
                model=model_name, contents=prompt, config=cfg
            )
            ms = int((time.perf_counter() - t0) * 1000)
            return json.loads(resp.text), ms

        except json.JSONDecodeError as e:
            last_err = e
            print(f"[retry {attempt}] JSON 파싱 실패: {e}")

        except Exception as e:
            last_err = e
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                wait = 20 * (attempt + 1)
                print(f"[retry {attempt}] 호출 한도 도달 — {wait}초 대기")
                time.sleep(wait)
            else:
                print(f"[retry {attempt}] 호출 실패: {msg[:100]}")

    raise RuntimeError(f"Gemini 호출 실패: {last_err}")
