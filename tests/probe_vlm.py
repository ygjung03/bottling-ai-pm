"""
확인용: gemini-3.5-flash-lite 가 이미지 입력을 받는지, 메뉴판을 읽는지.

메뉴판 사진 → VLM → 메뉴·가격 목록. 이 경로를 설계에 넣기 전에 실제로
되는지 본다 (U18 설계, 쟁점_2차흐름과_폼_0925.md 2-4).

  python -m tests.probe_vlm

무료 키로 호출한다. 이미지는 그 자리에서 그려 쓰므로 준비할 것이 없다.
"""
import io
import json
import time

from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types

from config.settings import GEMINI_API_KEY, GEMINI_MODEL

MENU = [
    ("감자튀김", "5,000"),
    ("치즈스틱", "6,000"),
    ("소떡소떡", "4,500"),
    ("닭강정 (소)", "12,000"),
    ("모둠튀김", "9,000"),
]


def make_image() -> bytes:
    """메뉴판처럼 생긴 PNG 를 그린다. 한국어가 들어가야 하므로 프로젝트 폰트를 쓴다."""
    img = Image.new("RGB", (520, 460), "#FFFBF0")
    d = ImageDraw.Draw(img)
    try:
        title = ImageFont.truetype("app/fonts/NanumGothic-Bold.ttf", 40)
        body = ImageFont.truetype("app/fonts/NanumGothic-Regular.ttf", 30)
    except OSError as e:
        raise SystemExit(f"폰트를 못 찾았다 — {e}. app/fonts/ 확인.")

    d.text((40, 30), "분식 메뉴", font=title, fill="#222222")
    d.line((40, 90, 480, 90), fill="#CC3333", width=3)
    y = 120
    for name, price in MENU:
        d.text((40, y), name, font=body, fill="#333333")
        d.text((380, y), price, font=body, fill="#333333")
        y += 62

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main() -> None:
    if not GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY 가 없다.")

    png = make_image()
    with open("tests/probe_vlm_input.png", "wb") as f:
        f.write(png)
    print(f"이미지 {len(png):,} bytes — tests/probe_vlm_input.png")

    prompt = (
        "이 사진은 가게 메뉴판이다. 적혀 있는 메뉴와 가격을 모두 읽어라.\n"
        "가격은 숫자만 적는다. 안 보이는 것은 null 로 둔다.\n"
        '{"메뉴": [{"이름": "...", "가격": 0}]}'
    )

    client = genai.Client(api_key=GEMINI_API_KEY)
    t0 = time.perf_counter()
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=png, mime_type="image/png"),
            prompt,
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    ms = int((time.perf_counter() - t0) * 1000)

    out = json.loads(resp.text)
    um = getattr(resp, "usage_metadata", None)
    print(f"\n모델 {GEMINI_MODEL} / {ms:,}ms")
    print(f"입력 토큰 {getattr(um, 'prompt_token_count', 0):,} / "
          f"출력 토큰 {getattr(um, 'candidates_token_count', 0):,}")
    print(json.dumps(out, ensure_ascii=False, indent=2))

    # 맞게 읽었는지 대조한다. 이름은 공백을 무시하고 본다.
    got = {m.get("이름", "").replace(" ", ""): m.get("가격") for m in out.get("메뉴", [])}
    print("\n대조")
    for name, price in MENU:
        key = name.replace(" ", "")
        want = int(price.replace(",", ""))
        mark = "O" if got.get(key) == want else "X"
        print(f"  {mark} {name} {want:,} → {got.get(key)}")


if __name__ == "__main__":
    main()
