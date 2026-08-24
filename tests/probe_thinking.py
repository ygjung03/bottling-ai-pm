"""
추론(thinking) 끄기 가능 여부 진단

여러 방식을 순서대로 시도해 무엇이 먹히는지 확인한다.
실행: python -m tests.probe_thinking
"""
import time
from config.settings import GEMINI_API_KEY, GEMINI_MODEL

PROMPT = "붕어빵 가게와 크래프트 맥주 펍의 협업 메뉴 3안을 JSON으로 만들어라. 각 안에 메뉴명, 구성, 페어링 맥주, 예상 원가를 포함하라."


def sep(t):
    print("\n" + "=" * 58)
    print(t)
    print("=" * 58)


# ── 1. 설치된 SDK 버전 확인 ──
sep("1. 설치 상태")
try:
    import google.generativeai as old_genai
    v = getattr(old_genai, "__version__", "unknown")
    print(f"  google-generativeai : {v}")
except ImportError:
    print("  google-generativeai : 미설치")

try:
    from google import genai as new_genai
    print(f"  google-genai        : 설치됨")
    HAS_NEW = True
except ImportError:
    print("  google-genai        : 미설치")
    HAS_NEW = False


# ── 2. 구 SDK로 thinking 시도 ──
sep("2. 구 SDK — thinking 옵션 시도")
try:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)

    variants = [
        ("thinking_config dict", {"response_mime_type": "application/json",
                                  "thinking_config": {"thinking_budget": 0}}),
        ("thinking_budget 직접", {"response_mime_type": "application/json",
                                  "thinking_budget": 0}),
        ("옵션 없음(기준)",      {"response_mime_type": "application/json"}),
    ]
    for label, cfg in variants:
        try:
            m = genai.GenerativeModel(GEMINI_MODEL, generation_config=cfg)
            t0 = time.perf_counter()
            r = m.generate_content(PROMPT)
            ms = int((time.perf_counter() - t0) * 1000)
            print(f"  [OK]   {label:<22} {ms/1000:.1f}s / {len(r.text)}자")
        except Exception as e:
            print(f"  [FAIL] {label:<22} {str(e)[:60]}")
except Exception as e:
    print(f"  구 SDK 사용 불가: {e}")


# ── 3. 신 SDK로 thinking 시도 ──
sep("3. 신 SDK — thinking 옵션 시도")
if not HAS_NEW:
    print("  google-genai 미설치. 아래 명령으로 설치 후 재실행:")
    print("      pip install google-genai")
else:
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)

        cases = [
            ("추론 끔 (budget=0)", types.GenerateContentConfig(
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_budget=0))),
            ("추론 최소 (budget=128)", types.GenerateContentConfig(
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_budget=128))),
            ("기본 (옵션 없음)", types.GenerateContentConfig(
                response_mime_type="application/json")),
        ]
        for label, cfg in cases:
            try:
                t0 = time.perf_counter()
                r = client.models.generate_content(
                    model=GEMINI_MODEL, contents=PROMPT, config=cfg)
                ms = int((time.perf_counter() - t0) * 1000)
                print(f"  [OK]   {label:<24} {ms/1000:.1f}s / {len(r.text)}자")
            except Exception as e:
                print(f"  [FAIL] {label:<24} {str(e)[:60]}")
    except Exception as e:
        print(f"  신 SDK 사용 불가: {e}")


# ── 4. 사용 가능 모델 목록 ──
sep("4. 사용 가능한 모델 (flash 계열)")
try:
    if HAS_NEW:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        names = [m.name for m in client.models.list()]
    else:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        names = [m.name for m in genai.list_models()]
    for n in sorted(set(names)):
        if "flash" in n.lower() or "lite" in n.lower():
            print("  ", n)
except Exception as e:
    print(f"  조회 실패: {e}")

sep("판정 기준")
print("  3번에서 '추론 끔'이 기본보다 확연히 빠르면 → 신 SDK로 교체")
print("  차이가 없으면 → 화면 설계를 백그라운드 방식으로 변경")
