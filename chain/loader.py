"""프롬프트 YAML 로더. 코드에 프롬프트 문자열을 넣지 않는다."""
import yaml
from functools import lru_cache
from config.settings import PROMPT_DIR


@lru_cache(maxsize=None)
def load(name: str) -> dict:
    return yaml.safe_load((PROMPT_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


def build(name: str, **vars_) -> str:
    """공통 규칙 + 페르소나 프롬프트를 합치고 변수를 치환한다."""
    common = load("common_rules")["rules"]
    body = load(name)["prompt"]
    return f"{common}\n\n{body}".format(**vars_)
