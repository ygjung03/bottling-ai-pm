"""
프로젝트 루트를 import 경로에 추가한다.

Streamlit 은 `streamlit run app/main.py` 실행 시 `app/` 을 sys.path 기준으로 잡는다.
따라서 그 위의 프로젝트 루트에 있는 db·config·context·chain 을 찾지 못한다.

각 페이지 파일 최상단에서 다른 import 보다 먼저 불러야 한다.

    import _path  # noqa: F401
    from app.auth import require_owner
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
