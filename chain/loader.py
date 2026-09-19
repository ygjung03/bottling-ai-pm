"""
프롬프트 YAML 로더. 코드에 프롬프트 문자열을 넣지 않는다.

[주의] str.format() 을 쓰지 않는다.
  프롬프트 본문에 출력 스키마용 JSON 중괄호가 포함되어 있어
  format() 이 이를 치환 변수로 오인한다.
  전달된 변수명만 골라서 치환한다.
"""
import re
import yaml
from functools import lru_cache

from config.settings import PROMPT_DIR


@lru_cache(maxsize=None)
def _load(name: str, mtime: float) -> dict:
    # mtime 은 캐시 키로만 쓴다. 파일이 바뀌면 값이 달라져 다시 읽는다.
    return yaml.safe_load((PROMPT_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


def load(name: str) -> dict:
    """
    프롬프트 YAML 을 읽는다. 파일이 바뀌지 않았으면 캐시를 쓴다.

    전에는 이름만으로 캐시해서, Streamlit 처럼 오래 사는 프로세스에서는
    프롬프트를 고쳐도 껐다 켜기 전까지 옛것을 썼다. 9/20 에 (3)을 고치고
    두 번 생성했는데 둘 다 옛 프롬프트로 돌았다. 수정 시각을 키에 넣어
    파일이 바뀌면 다시 읽게 했다. 안 바뀌면 stat 한 번뿐이라 비용은 없다.
    """
    return _load(name, (PROMPT_DIR / f"{name}.yaml").stat().st_mtime)


def render(template: str, **vars_) -> str:
    """{변수명} 형태만 치환한다. 그 외 중괄호는 그대로 둔다."""
    out = template
    for k, v in vars_.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def build(name: str, **vars_) -> str:
    """공통 규칙 + 페르소나 프롬프트를 합치고 변수를 치환한다."""
    common = load("common_rules")["rules"]
    body = load(name)["prompt"]
    text = render(f"{common}\n\n{body}", **vars_)

    # 치환되지 않은 변수가 남았는지 확인 (오타·누락 조기 발견)
    declared = set(load(name).get("inputs", []))
    leftover = {m for m in re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", text)
                if m in declared}
    if leftover:
        raise KeyError(f"{name}: 치환되지 않은 변수 {sorted(leftover)}")

    return text
