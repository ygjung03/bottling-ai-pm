"""Gemini 호출 래퍼. JSON 강제 출력."""
import json
import time
import google.generativeai as genai
from config.settings import GEMINI_API_KEY, GEMINI_MODEL

genai.configure(api_key=GEMINI_API_KEY)


def call(prompt: str, retry: int = 1) -> tuple[dict, int]:
    """
    JSON 응답을 강제하고 파싱해서 돌려준다.
    반환: (파싱된 dict, 소요 ms)
    """
    model = genai.GenerativeModel(
        GEMINI_MODEL,
        generation_config={"response_mime_type": "application/json"},
    )
    last_err = None
    for attempt in range(retry + 1):
        t0 = time.perf_counter()
        try:
            resp = model.generate_content(prompt)
            ms = int((time.perf_counter() - t0) * 1000)
            return json.loads(resp.text), ms
        except json.JSONDecodeError as e:
            last_err = e
            print(f"[retry {attempt}] JSON 파싱 실패: {e}")
        except Exception as e:
            last_err = e
            print(f"[retry {attempt}] 호출 실패: {e}")
    raise RuntimeError(f"Gemini 호출 실패: {last_err}")
