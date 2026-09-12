-- 2026-09-12 — T21 협력사 입력 폼
--
-- Supabase SQL Editor 에 그대로 붙여 실행한다.
-- 두 번 돌려도 안전하다.

-- ① 협력사가 지금 팔고 있는 메뉴와 가격
--
-- 협업이 완제품 매입 하나가 되면서(기획서 6-1) 셰프가 할 일이 신메뉴
-- 개발에서 「팔던 것 고르기」로 바뀌었다. 실제 판매가를 알아야 매입가
-- 제안에 근거가 생긴다 — 3,000원에 파는 것을 1,800원에 매입하겠다는
-- 제안은 상대도 계산해 볼 수 있는 값이다.
--
-- [{"메뉴": "붕어빵 3개", "가격": 3000}, ...]
ALTER TABLE partners
  ADD COLUMN IF NOT EXISTS menu_prices JSONB NOT NULL DEFAULT '[]'::jsonb;

-- ② 협의·연락이 가능한 때
--
-- 납품 가능 시간과 다르다. 물건을 가져다줄 수 있는 때와 전화로 이야기할
-- 수 있는 때가 다르기 때문이다. 매입가와 납품 수량은 결국 사람이 만나
-- 정해야 하므로(제안서 「협의가 필요한 사항」), 그 약속을 잡으려면
-- 이 값이 필요하다.
ALTER TABLE partners ADD COLUMN IF NOT EXISTS contact_slots TEXT;

-- ③ AI PM 을 쓰지 않은 협업도 남길 수 있게 한다
--
-- 기획 리드타임을 10/9 협업과 비교하려면 기준선이 필요한데(기획서 7-1),
-- 그 건에는 체인 출력이 없다. NOT NULL 이면 INSERT 단계에서 막힌다.
ALTER TABLE plans ALTER COLUMN context_snapshot DROP NOT NULL;
ALTER TABLE plans ALTER COLUMN final_output     DROP NOT NULL;

-- ④ 쓰지 않게 된 컬럼을 지운다
--
-- 남겨 두면 나중에 읽는 사람이 채워야 하는 값으로 오해한다.
-- 협력사 자료는 아직 들어오지 않았고 시드 한 행만 있어 잃을 것이 없다.
--
--   ingredients      완성품을 사 오므로 무엇으로 만드는지는 알 필요가 없다.
--                    변형 판단에 쓰는 것은 바틀링 보유 식재료다
--   collab_types     완제품 매입 하나로 정해져(기획서 6-1) 고를 것이 없다
--   sns_followers    도달을 측정하지 않아 목표를 세울 수 없다
--   wholesale_price  단가는 menu_prices 안에 메뉴마다 둔다. 메뉴마다 원가가
--                    달라 매장 전체에 하나만 두면 맞지 않는다
ALTER TABLE partners DROP COLUMN IF EXISTS ingredients;
ALTER TABLE partners DROP COLUMN IF EXISTS collab_types;
ALTER TABLE partners DROP COLUMN IF EXISTS sns_followers;
ALTER TABLE partners DROP COLUMN IF EXISTS wholesale_price;
