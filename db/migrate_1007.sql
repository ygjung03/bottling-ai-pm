-- 제미나이 사용량 기록 (2026-10-07)
--
-- [왜 필요한가]
--
-- 유료 키는 대표님 계정으로 발급된 것이고 청구도 대표님께 간다. 우리 쪽에서는
-- 얼마가 쓰였는지 볼 수 없어서, 10/6 에 쓴 금액을 되짚을 때 DB 에 남은 기획안
-- 건수로 역산해야 했다. 부른 쪽에서 직접 남겨 두면 그럴 일이 없다.
--
-- [기능과 키를 따로 남긴다]
--
-- 「메뉴 수집이니까 무료」로 묶지 않는다. 메뉴 수집은 지금 무료 키를 쓰지만,
-- 분당 한도에 여러 번 걸리면 그때만 유료로 넘기는 것을 검토 중이다. 그러면
-- 한 가게를 수집하는 동안 무료와 유료가 섞인다.
--
-- 그래서 kind(어느 기능)와 key_kind(어느 키)를 따로 두고, 한 번의 일에 대해
-- **쓴 키마다 한 줄씩** 남긴다. 섞인 수집은 두 줄이 된다.
--
--   kind        key_kind  calls  krw
--   메뉴 수집     무료       22     0     ← 한도에 걸리기 전까지
--   메뉴 수집     유료        8    18     ← 넘어간 뒤
--
-- [무료도 줄을 남기고 금액만 0 이다]
--
-- 무료 호출은 돈이 나가지 않지만 호출 수와 토큰은 남긴다. 하루 한도(500회)를
-- 얼마나 당겨썼는지도 봐야 하고, 「얼마나 썼나」와 「얼마가 나갔나」는 다른
-- 질문이다.
--
-- [환율을 같은 줄에 적는다]
--
-- 원화만 남기면 환율이 바뀔 때 지난 기록을 설명할 수 없다. 그때 쓴 환율을 함께
-- 넣어 두면 설정값을 바꿔도 지난 줄은 그대로다. 달러도 같이 남긴다 — 청구서는
-- 달러로 오므로 맞춰 볼 때 그쪽이 기준이다.
--
-- [지난 사용량은 들어 있지 않다]
--
-- 10/7 이전에 쓴 것은 기록이 없다. 이 테이블은 오늘부터 쌓인다. 그 전 금액은
-- 대표님께 청구 화면을 받아 맞춰 보는 수밖에 없다.

CREATE TABLE IF NOT EXISTS api_usage (
  id             BIGSERIAL PRIMARY KEY,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

  kind           TEXT    NOT NULL,          -- 기획안 생성 | 메뉴 수집
  key_kind       TEXT    NOT NULL,          -- 유료 | 무료
  model          TEXT,                      -- 단가가 모델마다 달라 함께 남긴다

  partner_id     BIGINT REFERENCES partners(id),
  -- 협력사 이름을 따로 두는 이유는 둘이다. 메뉴 수집은 아직 등록되지 않은
  -- 가게로도 돌 수 있어 id 가 없고, 협력사가 지워져도 그때 무엇에 썼는지는
  -- 남아야 한다.
  partner_name   TEXT,

  calls          INTEGER NOT NULL,          -- 제미나이를 부른 횟수
  input_tokens   INTEGER NOT NULL,
  output_tokens  INTEGER NOT NULL,

  -- 금액은 **유료 호출에만 매긴다.** 무료는 0 이다.
  usd            NUMERIC(12, 6) NOT NULL DEFAULT 0,
  krw            INTEGER        NOT NULL DEFAULT 0,
  krw_per_usd    NUMERIC(10, 2),            -- 그 줄을 넣을 때 쓴 환율

  note           TEXT                       -- 「1차」·「글 30건 중 28건 읽음」 등
);

COMMENT ON TABLE api_usage IS
  '제미나이 호출 사용량과 금액. 한 번의 일에 대해 쓴 키마다 한 줄. 금액은 유료 호출에만 매긴다';
COMMENT ON COLUMN api_usage.key_kind IS
  '그 줄이 쓴 키. 기능으로 짐작하지 않고 호출이 실제로 쓴 키를 적는다';
COMMENT ON COLUMN api_usage.krw_per_usd IS
  '그 줄을 넣을 때의 환율. 설정값을 바꿔도 지난 줄의 금액이 흔들리지 않게 한다';

-- 화면에서 날짜별·기능별로 합을 낸다 (관리 화면 「API 사용량」)
CREATE INDEX IF NOT EXISTS api_usage_created_idx ON api_usage (created_at DESC);
CREATE INDEX IF NOT EXISTS api_usage_kind_idx    ON api_usage (kind, created_at DESC);

-- ── RLS ─────────────────────────────────────────────────
-- 다른 테이블과 같은 기준이다 (db/rls_0928.sql). 읽기와 넣기만 허용하고
-- 지우기는 허용하지 않는다. 사용량은 고칠 일이 없어 update 도 열지 않는다 —
-- 근거 없이 넓히지 않는다는 원칙(②)에 맞춘다.
ALTER TABLE api_usage ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon read"  ON api_usage FOR SELECT TO anon USING (true);
CREATE POLICY "anon write" ON api_usage FOR INSERT TO anon WITH CHECK (true);
