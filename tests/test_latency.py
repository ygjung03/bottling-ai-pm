"""
응답 시간 실측 — W1 최우선 과제

[목적]
  명세서 추정(4단계 58초)과 실측이 어긋난다.
  기존 test_gemini_json.py는 최소 프롬프트·2안 기준으로 16초였으나,
  실제 프롬프트는 상권 컨텍스트·자원·제약·few-shot이 모두 포함되고 3안을 요구한다.

  4단계 합계가 2분에 근접하면 화면 설계(명세서 4-2)가 달라진다.
  진행 표시로 버틸지 비동기로 갈지가 갈리므로 지금 확인한다.

[측정 대상]
  1. 실제 길이 프롬프트에서의 단계별 소요
  2. 추론(thinking) 예산의 영향
  3. 경량(lite) 모델과의 차이

[선행 확인 결과 — probe_thinking]
  구 SDK(google-generativeai)는 thinking 옵션을 지원하지 않는다 → 신 SDK 사용
  thinking_budget=0 은 400 에러 (모델이 완전 비활성화를 허용하지 않음)
  thinking_budget=128 로 단일 호출 25.6s → 16.7s (35% 단축) 확인

[프롬프트 변경 이력]
  2026-08-24  (2) 셰프에 페어링 제약 추가
              - 논알콜 제외
              - "원가 절감형"이 저가 맥주를 뜻하지 않음을 명시
              사유: lite 모델이 원가 절감형에 논알콜(체리에이드)을 반복 선택.
                    바틀링 매출의 대부분이 맥주이므로 실익이 없다.

실행: python -m tests.test_latency
"""
import json
import statistics
import time
from datetime import datetime

from google import genai
from google.genai import types

from config.settings import GEMINI_API_KEY, GEMINI_MODEL

client = genai.Client(api_key=GEMINI_API_KEY)

REPEAT = 3          # 조건당 반복 횟수
SLEEP_STEP = 2      # 단계 사이 대기(초) — 분당 한도 회피
SLEEP_RUN = 8       # 회차 사이 대기(초)
SLEEP_COND = 15     # 조건 사이 대기(초)
# lite 계열은 할당량이 넉넉해 대기를 짧게 잡는다


# ══════════════════════════════════════════════
# 실제 길이에 가까운 입력 (가상 데이터)
# ══════════════════════════════════════════════

CONTEXT = """[대상 시점] 2026년 9월 3주 금요일

[실시간 인구]
- 뚝섬한강공원: 최근 4주 금요일 평균 혼잡도 '붐빔', 피크 18~21시
  (서울시 안내: "사람이 많아 붐빔이 느껴지고 도보 이동이 불편해요")
- 뚝섬역: 피크 17~19시, 한강공원보다 1~2시간 이름
- 12시간 예측: 19시 '붐빔'(8500~9000명) → 21시 '약간 붐빔'(7000~7500명)
  → 23시 '보통'(5000~5500명)

[실시간 상권]  ※ 뚝섬역 기준 (한강공원은 상권 데이터 없음)
- 제과/커피/패스트푸드: 결제 '바쁜', 최근 3시간 상승세 (건수 12, 20~25만원)
- 일식/중식/양식: 결제 '분주한' (건수 5, 65~70만원)
- 한식: '한산한' (건수 7, 25~30만원)
- 기타요식: '한산한' (건수 7, 9~10만원)
- 결제자 구성: 남성 63.1% / 40대 42.9%, 20대 28.9%

[날씨]
- 기온 23.1도, 습도 68%, 강수 없음

[분기 매출 프로파일]
- 주류업종 금요일 19~22시 매출 비중 34% (주중 최고)
- 20대 여성 비중 28% (타 요일 평균 21% 대비 높음)
- 제과업 금요일 15~18시 매출 비중 22%

[인근 행사 (30일 내)]
- 2026 광진 뮤직 페스타 / 8.29(토) 13:00~21:00 / 뚝섬 한강공원
  (플리마켓·체험부스·푸드트럭 운영)
"""

BEER_LIST = """- (논알콜) 체리에이드 / 8원·ml / 논알콜
- 바틀링 라거 / 12원·ml / 라거 / 4.8도 / 깔끔하고 청량함
- 37디그리스라거 / 14원·ml / 라거 / 5.0도 / 부드러운 목넘김
- 카이저돔 켈러비어 / 16원·ml / 켈러비어 / 4.9도 / 비여과, 고소함
- 맘마미아 / 16원·ml / 세종 / 5.2도 / 새콤하고 드라이함
- 산토리 프리미엄 몰츠 / 18원·ml / 재패니즈 라거 / 5.5도 / 몰트 풍미
- 캄캄 / 18원·ml / 스타우트 / 6.0도 / 로스팅 커피향
- 워터멜론 위트에일 / 20원·ml / 위트에일 / 4.5도 / 수박향, 가벼움
- 갈매기 IPA / 20원·ml / IPA / 6.5도 / 시트러스향, 쓴맛 진함
- 끽비어 삐약 ver2 / 20원·ml / 페일에일 / 5.4도 / 홉 향 강함
- 빅웨이브 / 20원·ml / 골든에일 / 4.4도 / 열대과일향
- 흔들흔들 / 20원·ml / 세션 IPA / 4.5도 / 가볍고 상큼함"""

KITCHEN = """- 사용 가능: 전자레인지, 에어프라이어, 인덕션 1구
- 화기(가스) 사용 불가. 전기만 가능
- 냉장고 1대, 냉동칸 소형 (하루치 보관)
- 바쁠 때는 5분 넘는 조리 불가. 데우거나 담는 수준
- 매장 앞 야외 테이블 2개, 외부 콘센트 1구
- 매장 수용 7인 내외, 테이크아웃 중심"""

PARTNER = """- 가게 이름: 떡붕
- 업종: 제과·디저트
- 대표 메뉴: 슈크림 붕어빵, 팥 붕어빵
- 보유 식재료: 팥앙금, 슈크림, 붕어빵 반죽, 우유, 버터, 흑임자
- 보유 장비: 붕어빵 기계(이동 가능, 2인이 들면 됨), 반죽기(매장 고정)
- 협업 가능 형태: 팝업 출장, 재료 납품
- 가능 일정: 주중 오후 2~6시
- SNS: 인스타 3,200명, 릴스 위주
- 절대 불가 조건: 주말 출장 불가 / 반죽 당일 소진 필요 / 냉장 보관 필수"""

CONSTRAINTS = """- C001: 준비 기간은 3일 이내로 제안한다.
- C002: 조리는 협력사 매장 또는 이동식 장비에서 완료하고, 바틀링은 반입·조합만 담당한다.
- C003: 예상 원가는 판매가의 40%를 넘지 않는다."""

FEWSHOT = """[사례 1]
- 입력 요약: 협력사=제과(붕어빵), 시점=10월 금요일 저녁, 상권=붐빔
- 출력 요약: 슈크림 붕어빵 3개 + 갈매기 IPA 500ml 세트 / 12,000원 / 완제품 반입
- 채택 사유: 준비 3일, 협력사 장비만 사용, 고가 라인 맥주 견인

[사례 2]
- 입력 요약: 협력사=화덕피자, 시점=5월 토요일 오후, 상권=매우 붐빔
- 출력 요약: 마르게리타 하프 + 워터멜론 위트에일 / 15,000원 / 야외 화덕 설치
- 채택 사유: 야외 공간 활용, SNS 인증 유도 성공"""


def p1_prompt() -> str:
    return f"""[출력 규칙]
- 반드시 지정된 JSON 스키마로만 응답한다. 설명 문장을 앞뒤에 붙이지 않는다.
- 입력에 제시되지 않은 수치를 만들어내지 않는다.
- 계산이 필요한 경우 직접 계산하지 않고, 입력에 있는 값을 그대로 인용한다.
- 정보가 없는 항목은 추정하지 말고 "데이터 없음"으로 표기한다.

당신은 서울 광진구 뚝섬유원지 상권을 분석하는 분석가다.
바틀링(셀프탭 크래프트 맥주 테이크아웃 펍, 15시 개점)의 협업 기획을
위해 대상 시점의 상권 상황을 진단한다.

[상권 데이터]
{CONTEXT}

[지시]
1. 대상 시점에 가장 유리한 공략 시간대를 1~2개 지정한다.
2. 그 시간대의 주 타겟 고객층을 특정한다.
3. 판단 근거가 된 지표를 입력에서 그대로 인용한다.
4. 데이터상 주의해야 할 점이 있으면 기록한다.

[출력 스키마]
{{"공략_시간대":[{{"시작":"19:00","종료":"22:00","선정_사유":"..."}}],
"타겟_고객층":{{"연령":"...","성별":"...","방문_목적":"..."}},
"근거_지표":["..."],"주의사항":["..."],"데이터_공백":["..."]}}"""


def p2_prompt(p1_out: str) -> str:
    return f"""[출력 규칙]
- 반드시 지정된 JSON 스키마로만 응답한다.
- 입력에 없는 수치를 만들어내지 않는다.

당신은 소상공인 협업 메뉴를 개발하는 셰프다.
바틀링과 협력사가 각자 보유한 자원만으로 실제 조리 가능한 메뉴를 제안한다.

[상권 분석 결과]
{p1_out}

[바틀링 자원]
{BEER_LIST}

[주방 여건]
{KITCHEN}

[협력사 자원]
{PARTNER}

[절대 제약 — 위반 시 해당 안을 폐기하고 다시 만든다]
{CONSTRAINTS}

[참고 사례]
{FEWSHOT}

[지시]
1. 메뉴 3안을 제안한다. 서로 다른 접근이어야 한다.
   (예: 조리 최소화형 / 화제성 중심형 / 원가 절감형)
2. 세 안은 동등하다. 순위를 매기지 않는다.
3. 각 안마다 바틀링 맥주 중 1종을 페어링으로 지정하고 이유를 쓴다.
   - 페어링은 반드시 알코올 맥주 중에서 고른다. 논알콜은 제외한다.
   - 바틀링 매출의 대부분이 맥주에서 발생하므로, "원가 절감형"이라 하더라도
     메뉴 원가를 낮추는 것이지 저가 맥주를 붙이라는 뜻이 아니다.
     세 안의 페어링이 모두 저가 라인에 몰리지 않게 한다.
4. 예상 원가는 협력사 식재료 기준으로 추산하되, 단가를 모르면 "산출 불가"로 표기한다.

[출력 스키마]
{{"메뉴안":[{{"안_id":"A","접근":"...","메뉴명":"...","구성":"...",
"필요_재료":[{{"재료":"...","제공처":"바틀링|협력사"}}],
"필요_장비":[{{"장비":"...","제공처":"..."}}],
"조리_난이도":"상|중|하","예상_원가":"...","판매가_제안":0,
"페어링_맥주":{{"메뉴명":"...","이유":"..."}},
"제약_충족_확인":["..."]}}]}}"""


def p3_prompt(p1_out: str, p2_out: str) -> str:
    return f"""[출력 규칙]
- 반드시 지정된 JSON 스키마로만 응답한다.

당신은 로컬 소상공인 협업의 홍보를 기획하는 마케터다.

[상권 분석 결과]
{p1_out}

[개발된 협업 메뉴 3안]
{p2_out}

[홍보 자산]
- 바틀링: 팔로워 2,400명 / 주 콘텐츠 릴스 / 반응 좋은 유형 맥주 따르는 클로즈업, 한강 노을
- 협력사: 팔로워 3,200명 / 주 콘텐츠 릴스
- 인근 행사: 2026 광진 뮤직 페스타 (8.29 뚝섬 한강공원)

[지시]
1. 먼저 세 안에 공통 적용되는 홍보 축을 1개 작성한다.
2. 그다음 각 안마다 메뉴 특성에 맞는 부분만 작성한다. 공통 내용을 반복하지 않는다.
3. 세 안의 우열을 판단하거나 순위를 매기지 않는다.
4. 양측 팔로워 규모에 맞는 현실적인 목표만 제시한다.

[출력 스키마]
{{"공통_홍보축":{{"타겟":"...","공략_시점":"...",
"채널별_전략":[{{"채널":"...","형식":"...","이유":"..."}}],"행사_연계":"..."}},
"안별_기획":[{{"안_id":"A","이벤트안":{{"명칭":"...","내용":"...","기간":"..."}},
"홍보_문구":"...","해시태그":["#..."],"차별_포인트":"...",
"준비물":["..."],"소요_기간":"..."}}]}}"""


def p4_prompt(p1_out: str, p2_out: str, p3_out: str) -> str:
    return f"""[출력 규칙]
- 반드시 지정된 JSON 스키마로만 응답한다.

당신은 바틀링 대표를 보좌하는 컨설턴트다.
앞선 세 단계의 결과를 검토하여 실행 순위를 확정하고 최종 기획안을 만든다.

[상권 분석] {p1_out}
[메뉴 3안]  {p2_out}
[홍보 기획] {p3_out}
[이 협력사가 추천된 이유] 도보 5분 거리의 제과업으로 이동식 조리가 가능하며,
저녁 시간대 매출 비중이 바틀링 영업시간과 겹칩니다. (점수 0.784)

[반드시 지킬 제약]
{CONSTRAINTS}

[최종 검수 체크리스트 — 세 안 각각에 대해 확인한다]
1. 협력사가 보유한 장비·식재료만으로 조리 가능한가
2. 준비 기간이 제약 범위 이내인가
3. 페어링 맥주가 메뉴 성격과 맞는가
4. 홍보 이벤트가 메뉴 내용과 연결되는가
5. 인용한 수치가 [상권 분석] 입력에 실제로 있는 값인가
6. 협력사의 불가 조건을 위반하지 않는가

[지시]
1. 세 안을 실행 가능성·원가·화제성·바틀링 매출 기여도로 평가한다.
   맥주 매출이 전체의 대부분이므로, 페어링 맥주가 고가 라인인지를 비중 있게 본다.
2. 순위 1~3위를 확정하고 각 안의 선정·후순위 사유를 명시한다.
3. 메뉴와 홍보가 어긋난 안이 있으면 홍보 쪽을 수정한다. 메뉴를 새로 만들지 않는다.
4. 체크리스트 1·2·6번을 통과하지 못한 안은 순위에서 제외하고 사유를 기록한다.

[출력 스키마]
{{"순위":[{{"순위":1,"안_id":"A","메뉴명":"...","선정_사유":"...","구성":"...",
"필요_재료":[],"필요_장비":[],"조리_난이도":"...","예상_원가":"...","판매가_제안":0,
"페어링_맥주":{{"메뉴명":"...","원_ml":20,"이유":"..."}},
"이벤트":{{"명칭":"...","내용":"..."}},"홍보_문구":"...","해시태그":[],
"실행_준비물":[],"소요_기간":"...","예상_리스크":[],
"추천_근거":{{"상권_지표":"...","자원_매칭":"...","유사_사례":"..."}}}}],
"제외":[],"체크리스트":[],"재생성_필요":false,"수정_내역":[]}}"""


# ══════════════════════════════════════════════
# 측정
# ══════════════════════════════════════════════

def call(prompt: str, model_name: str, thinking: int | None) -> tuple[str, int, int]:
    """반환: (응답 텍스트, 소요 ms, 출력 문자수)"""
    kw = {"response_mime_type": "application/json"}
    if thinking is not None:
        kw["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking)
    cfg = types.GenerateContentConfig(**kw)

    t0 = time.perf_counter()
    resp = client.models.generate_content(model=model_name, contents=prompt, config=cfg)
    ms = int((time.perf_counter() - t0) * 1000)
    return resp.text, ms, len(resp.text)


def call_retry(prompt, model_name, thinking, tries=3):
    """429(분당 한도)는 대기 후 재시도한다. 그 외 오류는 바로 올린다."""
    for t in range(tries):
        try:
            return call(prompt, model_name, thinking)
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                wait = 30 * (t + 1)
                print(f"      한도 도달 — {wait}초 대기 후 재시도 ({t+1}/{tries})")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("재시도 후에도 한도 초과")


def run_chain(model_name: str, thinking: int | None) -> dict | None:
    """4단계 순차 실행. 실패 시 None.

    주의: 단계 사이 대기는 측정값에 포함되지 않는다.
          각 단계의 소요는 call() 내부에서만 잰다.
    """
    try:
        p1, ms1, l1 = call_retry(p1_prompt(), model_name, thinking)
        time.sleep(SLEEP_STEP)
        p2, ms2, l2 = call_retry(p2_prompt(p1), model_name, thinking)
        time.sleep(SLEEP_STEP)
        p3, ms3, l3 = call_retry(p3_prompt(p1, p2), model_name, thinking)
        time.sleep(SLEEP_STEP)
        p4, ms4, l4 = call_retry(p4_prompt(p1, p2, p3), model_name, thinking)
    except Exception as e:
        print(f"    실패: {str(e)[:80]}")
        return None

    return {
        "p1": ms1, "p2": ms2, "p3": ms3, "p4": ms4,
        "total": ms1 + ms2 + ms3 + ms4,
        "out_len": l1 + l2 + l3 + l4,
        "p2_raw": p2, "final": p4,
    }


# 논알콜 품목 (bartling 라인업 기준)
NON_ALCOHOL = ["체리에이드"]

# 고가 라인 기준 (원/ml)
HIGH_PRICE = ["워터멜론 위트에일", "갈매기 IPA", "끽비어 삐약", "빅웨이브", "흔들흔들",
              "산토리", "캄캄"]


def quality_check(r: dict) -> dict:
    """시간만 보면 안 된다. 출력이 쓸 만한지 함께 확인한다."""
    out = {"3안 생성": False, "안_다양성": False, "페어링 지정": False,
           "논알콜 제외": False, "고가 포함": False,
           "순위 확정": False, "체크리스트": False}
    try:
        menus = json.loads(r["p2_raw"]).get("메뉴안", [])
        out["3안 생성"] = len(menus) == 3
        out["안_다양성"] = len({m.get("접근") for m in menus}) == len(menus)
        beers = [m.get("페어링_맥주", {}).get("메뉴명", "") for m in menus]
        out["페어링 지정"] = all(beers)
        # 논알콜을 페어링으로 고르지 않았는가
        out["논알콜 제외"] = not any(
            any(na in b for na in NON_ALCOHOL) for b in beers)
        # 고가 라인이 하나라도 포함되었는가
        out["고가 포함"] = any(
            any(hp in b for hp in HIGH_PRICE) for b in beers)
    except Exception:
        pass
    try:
        fin = json.loads(r["final"])
        out["순위 확정"] = len(fin.get("순위", [])) >= 1
        out["체크리스트"] = len(fin.get("체크리스트", [])) > 0
    except Exception:
        pass
    return out


def main() -> None:
    """
    측정 대상을 lite 계열로 한정한다.

    [사유] gemini-3.6-flash는 무료 일일 할당량이 소진되어 반복 측정이 불가능하다.
           1차 측정에서 120.5초로 확인되었고 lite 대비 8배 느려 채택 가능성이 없다.
           실제로 사용할 lite 계열을 정밀 비교하는 편이 유효하다.

    [기존 측정값 — 참고]
           gemini-3.6-flash / 기본 : 120.5초 (1회, 2026-08-24)
    """
    # (라벨, 모델, thinking_budget)
    conditions = [
        ("lite 기본",   "gemini-3.5-flash-lite", None),
        ("lite+128",    "gemini-3.5-flash-lite", 128),
        ("lite3.1+128", "gemini-3.1-flash-lite", 128),
    ]

    print("=" * 66)
    print(f"응답 시간 실측 — {datetime.now():%Y-%m-%d %H:%M}")
    print(f"조건당 {REPEAT}회 / 4단계 순차 / 신 SDK(google-genai)")
    print(f"한도 회피 대기: 단계 {SLEEP_STEP}s · 회차 {SLEEP_RUN}s · 조건 {SLEEP_COND}s")
    print("  ※ 대기 시간은 측정값에 포함되지 않습니다")
    print("  ※ 전체 5~8분 소요됩니다")
    print("=" * 66)

    results, samples = {}, {}
    for label, model_name, thinking in conditions:
        print(f"\n▶ {label}  [{model_name} / thinking={thinking}]")
        runs = []
        for i in range(REPEAT):
            if i > 0:
                time.sleep(SLEEP_RUN)
            r = run_chain(model_name, thinking)
            if r:
                runs.append(r)
                print(f"    {i+1}회 — "
                      f"(1){r['p1']/1000:.1f}s (2){r['p2']/1000:.1f}s "
                      f"(3){r['p3']/1000:.1f}s (4){r['p4']/1000:.1f}s "
                      f"= {r['total']/1000:.1f}s")
        if runs:
            results[label] = runs
            samples[label] = runs[-1]
            print(f"    → {len(runs)}/{REPEAT}회 성공")
        else:
            print(f"    → 전부 실패")
        time.sleep(SLEEP_COND)

    if not results:
        print("\n측정 실패. 모델명 또는 API 키를 확인하세요.")
        return

    # ── 시간 요약 ──
    print("\n" + "=" * 66)
    print("시간 (초)")
    print("=" * 66)
    print(f"{'조건':<12}{'(1)':>8}{'(2)':>8}{'(3)':>8}{'(4)':>8}{'합계':>9}{'편차':>8}{'회':>5}")
    print("-" * 66)
    for label, runs in results.items():
        avg = {k: statistics.mean(r[k] for r in runs) / 1000
               for k in ("p1", "p2", "p3", "p4", "total")}
        totals = [r["total"] / 1000 for r in runs]
        spread = max(totals) - min(totals)
        print(f"{label:<12}{avg['p1']:>8.1f}{avg['p2']:>8.1f}"
              f"{avg['p3']:>8.1f}{avg['p4']:>8.1f}{avg['total']:>9.1f}"
              f"{spread:>8.1f}{len(runs):>5}")

    # ── 품질 요약 ──
    print("\n" + "=" * 66)
    print("품질 (마지막 회차 기준)")
    print("=" * 86)
    keys = ["3안 생성", "안_다양성", "페어링 지정", "논알콜 제외", "고가 포함",
            "순위 확정", "체크리스트"]
    print(f"{'조건':<12}" + "".join(f"{k:>11}" for k in keys))
    print("-" * 86)
    for label, r in samples.items():
        q = quality_check(r)
        print(f"{label:<12}" + "".join(f"{('O' if q[k] else 'X'):>11}" for k in keys))

    # ── 판정 ──
    print("\n" + "=" * 66)
    print("판정")
    print("=" * 66)
    print(f"  명세서 추정        58.0초")
    print(f"  gemini-3.6-flash  120.5초  (1차 측정, 참고)")
    best_label, best = min(
        ((l, statistics.mean(r["total"] for r in v) / 1000) for l, v in results.items()),
        key=lambda x: x[1])
    for label, runs in results.items():
        t = statistics.mean(r["total"] for r in runs) / 1000
        mark = "  ← 최단" if label == best_label else ""
        print(f"  {label:<12}{t:>7.1f}초{mark}")
    print()
    if best <= 60:
        print("  → 동기 방식 가능. st.status 단계 표시로 충분")
    elif best <= 90:
        print("  → 단계별 결과를 즉시 노출하는 방식 권장 (대기 체감 완화)")
    else:
        print("  → 동기 방식 부적합. 백그라운드 처리 + 완료 알림 검토")
    print("\n  * 품질 표에 X가 있으면 시간이 짧아도 채택하지 않는다.")
    incomplete = [k for k, v in results.items() if len(v) < REPEAT]
    if incomplete:
        print(f"  * 경고 — 측정이 {REPEAT}회 미만인 조건: {', '.join(incomplete)}")
        print("    편차를 신뢰할 수 없으므로 재측정을 권한다.")

    # ── 저장 ──
    out = {
        "measured_at": datetime.now().isoformat(),
        "repeat": REPEAT,
        "conditions": [{"label": l, "model": m, "thinking": t} for l, m, t in conditions],
        "results": {k: [{kk: vv for kk, vv in r.items()
                         if kk not in ("final", "p2_raw")} for r in v]
                    for k, v in results.items()},
        "success_count": {k: len(v) for k, v in results.items()},
        "incomplete": [k for k, v in results.items() if len(v) < REPEAT],
        "quality": {k: quality_check(r) for k, r in samples.items()},
    }
    with open("latency_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n  → latency_result.json 저장")

    # ── 출력 샘플 비교 ──
    print("\n" + "=" * 66)
    print("메뉴 3안 비교 (품질 육안 확인)")
    print("=" * 66)
    for label, r in samples.items():
        print(f"\n[{label}]")
        try:
            for m in json.loads(r["p2_raw"]).get("메뉴안", []):
                beer = m.get("페어링_맥주", {}).get("메뉴명", "?")
                tag = ""
                if any(na in beer for na in NON_ALCOHOL):
                    tag = "  [논알콜]"
                elif any(hp in beer for hp in HIGH_PRICE):
                    tag = "  [고가]"
                print(f"  {m.get('안_id')}. {m.get('메뉴명')} "
                      f"({m.get('접근')}) — 페어링: {beer}{tag}")
        except Exception as e:
            print(f"  파싱 실패: {e}")


if __name__ == "__main__":
    main()
