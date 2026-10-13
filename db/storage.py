"""
Supabase Storage 에서 파일을 받아 온다.

[무엇에 쓰나]
  협력사가 폼에 올린 메뉴판 사진이다. 구글 폼에 올라온 파일을 Apps Script 가
  `partner-menus` 버킷으로 옮기고, 그 **버킷 안 경로**를 `partners.menu_photo_url`
  에 남긴다 (`scripts/google_form_sync.gs`). 전체 URL 이 아니라 경로다.

  여기서 받아 온 내용을 `chain.gemini.call(images=...)` 에 넘겨 메뉴를 읽는다.

[종류를 짐작하지 않는다]
  사진은 jpeg 일 수도 png 일 수도 heic 일 수도 있다. 확장자로 짐작하지 않고
  받을 때 서버가 알려준 종류를 함께 돌려준다. 안 알려주면 None 이고, 부르는
  쪽이 그 파일을 건너뛴다 — 틀린 종류로 넘기면 모델이 못 읽는다(작업 원칙 ③).

[실패해도 흐름을 멈추지 않는다]
  사진 한 장을 못 받아도 나머지로 읽으면 된다 (작업 원칙 ⑤). 못 받은 것은
  빼고 돌려주고, 왜 못 받았는지는 함께 넘긴다.
"""
from db.client import get_client

BUCKET = "partner-menus"


def download(path: str, bucket: str = BUCKET) -> tuple[bytes, str] | None:
    """
    경로 하나를 받아 (내용, 종류)로 돌려준다. 못 받으면 None.

    종류를 못 알아내면 받은 내용이 있어도 None 이다 — 위 설명 참고.
    """
    try:
        store = get_client().storage.from_(bucket)
        data = store.download(path)
    except Exception as e:
        print(f"[사진 받기 실패] {path}: {type(e).__name__}: {e}")
        return None
    if not data:
        return None

    mime = sniff(data)
    if not mime:
        print(f"[사진 종류를 모름] {path} — 건너뛴다")
        return None
    return data, mime


def download_all(paths: list[str] | None,
                 bucket: str = BUCKET) -> tuple[list[tuple[bytes, str]], list[str]]:
    """
    경로 목록을 받아 (받은 것들, 못 받은 경로들)로 돌려준다.

    부르는 쪽이 「몇 장 중 몇 장을 읽었는지」를 화면에 적을 수 있어야 해서
    못 받은 것을 조용히 버리지 않는다.
    """
    got, failed = [], []
    for p in paths or []:
        one = download(p, bucket)
        if one:
            got.append(one)
        else:
            failed.append(p)
    return got, failed


# 파일 앞머리로 종류를 가린다. Storage 가 내용만 돌려주므로 여기서 본다.
# 폼이 받는 것은 사진이고, 휴대폰으로 찍어 올리면 heic 가 섞인다.
MAGIC = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
]


def sniff(data: bytes) -> str | None:
    """
    파일 앞머리를 보고 종류를 돌려준다. 모르면 None.

    webp·heic 는 앞 네 바이트가 길이라서 그 뒤의 표시를 본다.
    """
    for mark, mime in MAGIC:
        if data.startswith(mark):
            return mime
    head = data[:16]
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"mif1", b"msf1"):
            return "image/heic"
        if brand == b"avif":
            return "image/avif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None
