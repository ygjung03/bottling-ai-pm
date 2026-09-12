"""
협력사 행 만들기 — 구글폼을 보내기 전에 한 번 돌린다 (T21)

[담당] B

협력사가 정해지면 상호와 업종으로 행을 만든다. 나머지 항목은 협력사가
구글폼에 채우면 Apps Script 가 이 행을 갱신한다
(scripts/google_form_sync.gs · docs/협력사_구글폼_문항.md).

초대 코드를 발급해 미리 채운 폼 주소까지 찍어 준다. 그 주소를 그대로
협력사에 보내면 된다.

실행
  python -m scripts.new_partner "상호" "업종"
  python -m scripts.new_partner "상호" "업종" --link "https://docs.google.com/..."

[상호를 인자로 받는 이유]
  저장소가 공개다. 협력사 상호를 파일에 적어 두면 커밋에 남는다.
  실행할 때만 주고 DB 에만 들어가게 한다.

[업종은 목록에 있는 것만 받는다]
  context/builder.py 의 INDUSTRY_MAP 키여야 그 업종의 상권 매출을
  실을 수 있다 (명세서 3-2). 목록에 없는 값을 넣으면 매출 데이터 없이
  기획이 돌아가므로 여기서 막는다.
"""
import secrets
import sys
from urllib.parse import quote

from context.builder import INDUSTRY_MAP
from db.client import get_client

# 구글폼의 「확인 코드」 문항 id.
#
# 「양식 미리 작성」으로 만든 미리채운 링크의 entry 번호다. 폼 문항을
# 지우고 다시 만들면 번호가 바뀌므로, 링크가 이상하면 이 값을 먼저 본다.
# 모르면 --link 로 미리채운 링크를 직접 넘긴다.
FORM_URL = None          # 예) "https://docs.google.com/forms/d/e/.../viewform"
CODE_ENTRY = None        # 예) "entry.123456789"


def new_code() -> str:
    """
    초대 코드를 발급한다.

    코드가 곧 신원이다(app/auth.py). 무작위로 만들고 화면에 한 번만
    보여준다. 저장소에 적어 두면 코드 구실을 못 한다.
    """
    return secrets.token_urlsafe(12)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        print("업종은 아래 중 하나여야 한다.")
        for k in INDUSTRY_MAP:
            print(f"  {k}")
        return

    name, category = args[0].strip(), args[1].strip()
    if category not in INDUSTRY_MAP:
        print(f"업종 '{category}' 는 목록에 없다. 아래 중 하나를 쓴다.")
        for k in INDUSTRY_MAP:
            print(f"  {k}")
        return

    cli = get_client()

    # 같은 상호가 이미 있으면 코드를 새로 발급하지 않는다.
    # 이미 보낸 링크가 죽고, 협력사가 채운 내용을 못 찾게 된다.
    try:
        cur = (cli.table("partners").select("id, name, invite_code")
               .eq("name", name).execute().data or [])
    except Exception as e:
        print(f"조회 실패: {e}")
        return

    if cur:
        row = cur[0]
        print(f"이미 있다 — id={row['id']} {row['name']}")
        print(f"초대 코드: {row['invite_code']}")
        print("코드를 새로 발급하지 않는다. 이미 보낸 링크가 죽는다.")
        return

    code = new_code()
    try:
        rows = cli.table("partners").insert({
            "name": name,
            "category": category,
            "invite_code": code,
        }).execute().data or []
    except Exception as e:
        print(f"등록 실패: {e}")
        return

    print(f"등록 완료 — id={rows[0]['id']} {name} ({category})")
    print(f"초대 코드: {code}")
    print("이 값은 여기에만 표시된다. 지금 적어 둘 것.")

    link = None
    if "--link" in sys.argv:
        # 미리채운 링크를 직접 넘긴 경우. 그 안의 코드만 바꿔 준다.
        base = sys.argv[sys.argv.index("--link") + 1]
        import re
        link = re.sub(r"(entry\.\d+=)[^&]*", rf"\g<1>{quote(code)}", base)
    elif FORM_URL and CODE_ENTRY:
        link = f"{FORM_URL}?usp=pp_url&{CODE_ENTRY}={quote(code)}"

    if link:
        print("\n협력사에 보낼 주소")
        print(f"  {link}")
    else:
        print("\n폼 주소를 만들려면 둘 중 하나가 필요하다.")
        print("  · 이 파일의 FORM_URL·CODE_ENTRY 를 채운다")
        print("  · --link 로 미리채운 링크를 넘긴다")
        print("    (폼 ⋮ → 「양식 미리 작성」 → 확인 코드 아무 값 → 링크 복사)")


if __name__ == "__main__":
    main()
