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
CREATE TABLE IF NOT EXISTS sales_profile (
  id            BIGSERIAL PRIMARY KEY,
  quarter       TEXT NOT NULL,          -- 2026Q2
  area_code     TEXT NOT NULL,
  industry      TEXT NOT NULL,
  weekday       TEXT NOT NULL,
  time_band     TEXT NOT NULL,
  age_group     TEXT,
  gender        TEXT,
  sales_amount  BIGINT,
  sales_ratio   NUMERIC(5,2),
  UNIQUE (quarter, area_code, industry, weekday, time_band, age_group, gender)
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
  partner_source    TEXT    NOT NULL DEFAULT 'recommended',  -- recommended | manual
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  target_date       DATE,

  context_snapshot  TEXT    NOT NULL,   -- 컨텍스트 빌더 출력 원문 (재현·검증용)
  p1_output         JSONB,
  p2_output         JSONB,
  p3_output         JSONB,
  final_output      JSONB   NOT NULL,

  auto_check        JSONB,              -- 1층 자동 검증 결과
  latency_ms        INTEGER,
  prompt_version    TEXT,               -- prompts/ git hash

  adopted_option    TEXT,               -- 채택한 안_id (A|B|C)
  status            TEXT    NOT NULL DEFAULT 'generated',
                    -- generated | adopted | rejected | executed
  reject_reason     TEXT,
  executed_at       DATE,
  sales_before      BIGINT,             -- 직전 같은 요일 총매출
  sales_after       BIGINT,             -- 실행일 총매출
  performance       JSONB,              -- {insta_reach, insta_save, coupon_new, coupon_return_rate}
  rubric_score      JSONB,              -- {실행가능성:4, 자원정합성:3, ...}
  note              TEXT
);
CREATE INDEX IF NOT EXISTS idx_plans_status ON plans (status, created_at DESC);
