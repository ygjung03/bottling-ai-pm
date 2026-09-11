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

-- ② AI PM 을 쓰지 않은 협업도 남길 수 있게 한다
--
-- 기획 리드타임을 10/9 협업과 비교하려면 기준선이 필요한데(기획서 7-1),
-- 그 건에는 체인 출력이 없다. NOT NULL 이면 INSERT 단계에서 막힌다.
ALTER TABLE plans ALTER COLUMN context_snapshot DROP NOT NULL;
ALTER TABLE plans ALTER COLUMN final_output     DROP NOT NULL;
