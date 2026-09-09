"""
네이버 블로그 본문 수집 가능성 확인 — U17 시험

「가게명 + 메뉴명」 언급 수만 세는 것을 넘어, 본문에서 **메뉴와 가격을
뽑을 수 있는지**를 본다. 되면 협력사 입력 폼(T21)의 부담이 줄고,
매입가 제안의 근거(U18)에 시중가가 생긴다.

[플레이스와 다른 길이다]
  9/3 에 시험한 플레이스 메뉴 API 는 첫 요청부터 캡차였다
  (tests/probe_naver_menu.py). 블로그는 그것과 별개 경로다.

[주의] 네이버 이용약관상 자동화 수집은 제재 대상이 될 수 있다.
  본문이 열린다고 마음껏 긁어도 된다는 뜻이 아니다. 후보 5～10곳으로
  제한하고, 실패 시 지도 링크만 제공하는 대체 경로를 항상 남긴다
  (유행메뉴 검색 설계).

확인하는 것
  1. RSS 로 본문을 받을 수 있는가        → 요약만 온다 (약 350자)
  2. 본문 페이지를 받을 수 있는가        → 받아진다
  3. 음식점 후기에 가격이 적혀 있는가    → 검색 API 키가 있어야 표본을 모은다

실행
  python -m tests.probe_naver_blog
  python -m tests.probe_naver_blog <블로그ID> <글번호>
"""
import re
import sys

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

# 가격 표기. "8,000원", "8000 원", "₩8,000" 을 모두 잡는다
PRICE = re.compile(r"(?:₩\s*)?\d{1,3}(?:,\d{3})+\s*원?|\d{4,6}\s*원")


def strip_html(html: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def fetch_body(blog_id: str, log_no: str) -> str | None:
    """
    본문을 가져온다.

    블로그 글은 iframe 안에 있어 blog.naver.com/{id}/{logNo} 로는 껍데기만 온다.
    PostView.naver 가 본문을 직접 준다. 모바일(m.blog.naver.com)도 열리나
    가져오는 양이 3분의 1 수준이다.
    """
    url = f"https://blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}"
    try:
        r = requests.get(url, headers=UA, timeout=20)
    except Exception as e:
        print(f"  요청 실패: {e}")
        return None

    if not r.ok:
        print(f"  HTTP {r.status_code}")
        return None
    if "se-main-container" not in r.text and "postViewArea" not in r.text:
        print("  본문 컨테이너를 찾지 못함 — 구조가 바뀌었거나 접근이 막혔다")
        return None
    return strip_html(r.text)


def main() -> None:
    args = sys.argv[1:]
    blog_id = args[0] if args else "naverofficial"
    log_no = args[1] if len(args) > 1 else "224400531915"

    print(f"대상 blog.naver.com/{blog_id}/{log_no}")
    body = fetch_body(blog_id, log_no)
    if not body:
        raise SystemExit("본문 수집 불가")

    prices = PRICE.findall(body)
    print(f"  본문 {len(body):,}자")
    print(f"  가격 표기 {len(prices)}건" + (f" — {prices[:8]}" if prices else ""))
    print()
    print("  앞부분:", body[:200])
    print()
    print("[남은 것] 검색 API 키가 있어야 음식점 후기를 표본으로 모을 수 있다.")
    print("  네이버 개발자센터에서 애플리케이션을 등록하고 Client ID/Secret 을 받는다.")


if __name__ == "__main__":
    main()
