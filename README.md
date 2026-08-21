# 바틀링 AI PM

소상공인 협업 기획을 자동화하는 AI 프로젝트 매니저.
서울 AI재단 소상공인 AI활용 지원사업 · 청년팀 소복소복 × 바틀링

---

## 담당 구분

| 폴더 | 담당 | 내용 |
|---|---|---|
| `collectors/` | **A** | 공공 API 호출·수집 |
| `ingest/` | **A** | 전처리 · DB 적재 |
| `recommender/` | **A** | 파트너 추천 스코어링 |
| `context/` | **B** | 컨텍스트 빌더 (수치 → 자연어) |
| `prompts/` | **B** | 페르소나 프롬프트 YAML |
| `chain/` | **B** | 체인 실행기 · 자동 검증 |
| `app/` | **B** | Streamlit 화면 |
| `db/` `config/` | 공용 | 스키마 · 설정 |

**경계는 DB다.** A가 채우고 B가 읽는다. 스키마만 합의되면 서로 막히지 않는다.

---

## 시작하기

```bash
git clone <repo>
cd bottling-ai-pm

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # 값 채우기
```

`.env`는 절대 커밋하지 않는다. GitHub Actions는 Secrets를 사용한다.

---

## DB 초기화

Supabase 콘솔 → SQL Editor에서 `db/schema.sql` 전체 실행.

테이블 7개가 생성된다.

| 테이블 | 채우는 사람 |
|---|---|
| `partners` | 협력사 입력 폼 |
| `beers` | 관리 화면 (월 1회 교체) |
| `market_context` | **수집기 (30분)** |
| `sales_profile` | 배치 (분기) |
| `nearby_stores` | 배치 (월) |
| `events` | 배치 (일) |
| `plans` | 시스템 생성 + 대표님 피드백 |

---

## 실행

```bash
# 실시간 수집 1회 (로컬 테스트)
python -m collectors.realtime

# Streamlit
streamlit run app/main.py
```

---

## 일정

| 시점 | 내용 |
|---|---|
| ~9/20 | **시스템 완성** |
| 9/21~10/16 | 실증 (협업 2~3건) |
| ~10/18 | 최종 산출물 |

상세는 「개발명세서」 참조.
