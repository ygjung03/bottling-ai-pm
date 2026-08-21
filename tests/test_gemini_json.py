"""
T06 — Gemini JSON 출력 검증

확인 대상 3가지
  1. 중첩 JSON 스키마를 지키는가
  2. 한국어 키를 그대로 쓰는가 (영문으로 바꿔버리면 프롬프트 전체를 다시 써야 함)
  3. 1회 응답 시간

실행: python -m tests.test_gemini_json
"""
import json
from chain.gemini import call

PROMPT = """
아래 스키마로만 응답하라. 설명 문장을 붙이지 마라.

{
  "메뉴안": [
    {
      "안_id": "A",
      "메뉴명": "...",
      "페어링_맥주": {"메뉴명": "...", "이유": "..."},
      "필요_재료": [{"재료": "...", "제공처": "바틀링|협력사"}]
    }
  ]
}

붕어빵 가게와 크래프트 맥주 펍의 협업 메뉴 2안을 만들어라.
"""

if __name__ == "__main__":
    out, ms = call(PROMPT)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n소요 {ms}ms")

    keys = list(out.keys())
    print("\n--- 검증 ---")
    print(f"1. 최상위 키          : {keys}")
    print(f"2. 한국어 키 유지     : {'메뉴안' in out}")
    if out.get("메뉴안"):
        item = out["메뉴안"][0]
        print(f"3. 중첩 객체 유지     : {isinstance(item.get('페어링_맥주'), dict)}")
        print(f"4. 하위 키           : {list(item.keys())}")
