-- 바틀링 AI PM — DB 스키마 (테이블 7개)
-- Supabase SQL Editor에서 전체 실행

-- ============================================================
-- 〔협업 주체〕 사람이 입력·관리
-- ============================================================

-- 협력사 마스터
CREATE TABLE IF NOT EXISTS partners (
  id                BIGSERIAL PRIMARY KEY,
  name              TEXT        NOT NULL,
  category          TEXT        NOT NULL,           -- 제과·디저트 / 피자 / 분식 / 카페 ...
  signature_menu    TEXT,
  ingredients       TEXT[]      NOT NULL DEFAULT '{}',   -- 셰프의 핵심 입력
  equipment         TEXT[]      NOT NULL DEFAULT '{}',
  collab_types      TEXT[]      NOT NULL DEFAULT '{}',   -- 팝업출장 / 재료납품 / 콘텐츠
  available_slots   TEXT,
  sns_channel       TEXT,
  sns_followers     INTEGER,
  sns_content_type  TEXT,                            -- 릴스 / 피드 / 스토리
  wholesale_price   INTEGER,                         -- 완제품 납품 희망 단가 (원). 선택 입력
  blockers          TEXT[]      NOT NULL DEFAULT '{}',   -- 절대 불가 조건 (하드 제약)
  lat               DOUBLE PRECISION,
  lng               DOUBLE PRECISION,
  invite_code       TEXT UNIQUE NOT NULL,            -- 폼 접근용
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 바틀링 맥주 라인업 (월 1회 교체, 이력 보존)
CREATE TABLE IF NOT EXISTS beers (
  id            BIGSERIAL PRIMARY KEY,
  name          TEXT NOT NULL,
  price_per_ml  NUMERIC(5,1) NOT NULL,     -- 원/ml
  style         TEXT,                      -- 라거 / IPA / 위트에일 / 켈러비어
  abv           NUMERIC(3,1),
  ibu           INTEGER,
  flavor_notes  TEXT[],                    -- {시트러스, 쌉쌀함}
  brewery       TEXT,
  is_alcohol    BOOLEAN NOT NULL DEFAULT true,
  is_fixed      BOOLEAN NOT NULL DEFAULT false,
  valid_from    DATE NOT NULL,
  valid_to      DATE,                      -- NULL = 현재 판매 중
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_beers_valid ON beers (valid_to, valid_from DESC);

-- ============================================================
-- 〔상권 데이터〕 배치로 자동 수집
-- ============================================================

-- 상권 시계열 (30분 배치 누적) *** 과거 조회 불가 — 즉시 수집 시작 ***
-- 통합 API(citydata) 1회 호출로 인구·상권·날씨를 모두 수신한다.
CREATE TABLE IF NOT EXISTS market_context (
  id                BIGSERIAL PRIMARY KEY,
  collected_at      TIMESTAMPTZ NOT NULL,   -- API의 PPLTN_TIME (예정 시각 아님)
  spot              TEXT        NOT NULL,   -- 뚝섬한강공원 | 뚝섬역
  area_cd           TEXT,                   -- POI093 | POI025

  -- 인구
  congestion_level  TEXT,                   -- 여유 | 보통 | 약간 붐빔 | 붐빔
  congestion_msg    TEXT,                   -- 서울시가 제공하는 완성 문장
  population_min    INTEGER,
  population_max    INTEGER,
  ppltn_rates       JSONB,                  -- 성별·연령대·거주/비거주 비중
  forecast_12h      JSONB,                  -- 12시간 예측 배열

  -- 상권 (뚝섬한강공원은 데이터 없음 → NULL)
  cmrcl_level       TEXT,                   -- 한산한 | 보통 | 바쁜 | 분주한
  pay_count         INTEGER,
  pay_amt_min       BIGINT,
  pay_amt_max       BIGINT,
  food_pay          JSONB,                  -- 음식·음료 중분류별 결제 현황
  cmrcl_rates       JSONB,                  -- 결제자 성별·연령 비중

  -- 날씨
  temp              NUMERIC(4,1),
  humidity          INTEGER,
  precpt_type       TEXT,                   -- 없음 | 비 | 눈 ...
  pcp_msg           TEXT,

  raw               JSONB,                  -- 원본 전체 보존
  UNIQUE (collected_at, spot)
);
CREATE INDEX IF NOT EXISTS idx_mc_spot_time ON market_context (spot, collected_at DESC);

-- 분기 매출 프로파일
--
-- 단위는 상권이 아니라 행정동(자양3동)이다. 바틀링이 서울시 주요상권 82곳에
-- 포함되지 않아 상권코드를 쓸 수 없다 (명세서 2-4).
--
-- 축이 조합되지 않고 독립 합계로만 온다. "금요일 × 20대 × 여성" 같은 행이
-- 원본에 없어 컬럼 조합형으로는 담을 수 없다. 축별 비중을 JSONB 로 둔다.
--
-- [2026-09-08] 금액 비중에 더해 건수 비중을 담는다 (명세서 9-1 M3).
--   원본 CSV 에 축마다 금액과 건수가 모두 있는데 8/29 적재에서 금액만 넣었다.
--   그래서 전체 객단가(sales_amount / sales_count)는 나와도 "17-21시 손님이
--   한 번에 얼마 쓰나"를 낼 수 없었다.
--
--   구간 객단가 = (금액비중 × sales_amount) / (건수비중 × sales_count)
--
--   실측으로 호프-간이주점 2026Q2 는 21-24시 49,539원 / 17-21시 43,094원이다.
--   협업 메뉴의 판매가와 매입가를 정할 때 전체 평균보다 정확한 근거가 된다.
CREATE TABLE IF NOT EXISTS sales_profile (
  id                    BIGSERIAL PRIMARY KEY,
  quarter               TEXT NOT NULL,   -- 2026Q2
  dong_code             TEXT NOT NULL,   -- 행정안전부 주민등록 행정기관코드
  dong_name             TEXT NOT NULL,   -- 자양3동
  industry_code         TEXT,
  industry_name         TEXT NOT NULL,   -- 호프-간이주점 / 제과점 ...
  sales_amount          BIGINT,          -- 매출 금액 (원)
  sales_count           INTEGER,         -- 매출 건수 (거래 건수. 점포 수가 아니다)

  -- 매출 금액 기준 비중
  weekday_ratio         JSONB,           -- {"월": 0.12, ..., "일": 0.18}
  timeband_ratio        JSONB,           -- {"00-06": 0.03, ..., "21-24": 0.21}
  gender_ratio          JSONB,           -- {"남": 0.52, "여": 0.48}
  age_ratio             JSONB,           -- {"10": 0.02, ..., "60_이상": 0.09}

  -- 매출 건수 기준 비중. 위와 짝을 이뤄 축별 객단가를 만든다
  weekday_count_ratio   JSONB,
  timeband_count_ratio  JSONB,
  gender_count_ratio    JSONB,
  age_count_ratio       JSONB,

  UNIQUE (quarter, dong_code, industry_code)
);

-- 반경 점포 (월 배치)
CREATE TABLE IF NOT EXISTS nearby_stores (
  store_id      TEXT PRIMARY KEY,       -- 상가업소번호
  name          TEXT NOT NULL,
  category_l    TEXT,
  category_m    TEXT,
  category_s    TEXT,
  address       TEXT,
  lat           DOUBLE PRECISION,
  lng           DOUBLE PRECISION,
  distance_m    INTEGER,
  score         NUMERIC(6,3),
  score_detail  JSONB,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ns_score ON nearby_stores (score DESC);

-- 행사
CREATE TABLE IF NOT EXISTS events (
  id          BIGSERIAL PRIMARY KEY,
  source      TEXT NOT NULL,            -- seoul_api | gwangjin_board
  title       TEXT NOT NULL,
  place       TEXT,
  start_date  DATE,
  end_date    DATE,
  lat         DOUBLE PRECISION,
  lng         DOUBLE PRECISION,
  distance_m  INTEGER,
  is_free     BOOLEAN,
  url         TEXT,
  UNIQUE (source, title, start_date)
);

-- ============================================================
-- 〔생성 결과〕
-- ============================================================

CREATE TABLE IF NOT EXISTS plans (
  id                BIGSERIAL PRIMARY KEY,
  partner_id        BIGINT REFERENCES partners(id),
  partner_source    TEXT    NOT NULL DEFAULT 'recommended',
                    -- recommended | manual | menu_search
  trend_menu        TEXT,               -- 메뉴 검색으로 시작한 경우 그 메뉴명
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

  date_mode         TEXT    NOT NULL DEFAULT 'fixed',  -- fixed | range
  target_date       DATE,               -- 확정된 실행일
  range_from        DATE,               -- 희망 기간 시작 (date_mode='range')
  range_to          DATE,               -- 희망 기간 끝
  date_reason       TEXT,               -- 그 날짜를 고른 이유 (range 인 경우)

  context_snapshot  TEXT    NOT NULL,   -- 컨텍스트 빌더 출력 원문 (재현·검증용)
  p1_output         JSONB,
  p2_output         JSONB,
  p3_output         JSONB,
  final_output      JSONB   NOT NULL,

  menu_images       JSONB,              -- {"A": "img/plans/...png", "B": null}
  image_model       TEXT,               -- 생성 모델명 (재현용)

  auto_check        JSONB,              -- 1층 자동 검증 결과
  latency_ms        INTEGER,            -- 4단계 합계 (이미지 제외)
  image_latency_ms  INTEGER,            -- 이미지 생성은 별도 호출이라 분리한다
  prompt_version    TEXT,               -- prompts/ git hash

  adopted_option    TEXT,               -- 채택한 안_id (A|B|C)
  status            TEXT    NOT NULL DEFAULT 'generated',
                    -- generated | adopted | rejected | executed
  reject_reason     TEXT,
  executed_at       DATE,
  agreed_wholesale  INTEGER,            -- 협의로 확정된 매입가 (협력사에게 주는 돈)
  retail_price      INTEGER,            -- 실제 판매가 (손님에게 받는 돈)
  sold_qty          INTEGER,            -- 판매 수량
  sales_before      BIGINT,             -- 직전 같은 요일 총매출
  sales_after       BIGINT,             -- 실행일 총매출
  performance       JSONB,              -- 쿠폰 앱 지표 (명세서 2-7)
  rubric_score      JSONB,              -- {실행가능성:4, 자원정합성:3, ...}
  lead_time_min     INTEGER,            -- 기획 착수부터 제안서 완성까지 (분). 주 지표
  note              TEXT
);
CREATE INDEX IF NOT EXISTS idx_plans_status ON plans (status, created_at DESC);
