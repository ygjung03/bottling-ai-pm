-- 2026-09-18 — 기획안 회차
--
-- Supabase SQL Editor 에 그대로 붙여 실행한다.
-- 두 번 돌려도 안전하다.

-- 기획안을 1차·2차로 나눈다.
--
--   1차  협력사가 아무것도 입력하기 전. 블로그 후기에서 확인한 메뉴·판매가만으로
--        만들어 제안서를 먼저 보낸다. 납품가·납품 요일·제약은 비어 있는 것이 정상이다.
--   2차  협력사가 하겠다고 해서 구글 폼을 낸 뒤. 나머지 값을 받아 다시 만든다.
--
-- 회차가 없으면 같은 협력사의 기획안이 여러 건 쌓였을 때 어느 것이 제안서로
-- 나갔고 어느 것이 협의 뒤 것인지 구분할 수 없다.
ALTER TABLE plans ADD COLUMN IF NOT EXISTS round SMALLINT NOT NULL DEFAULT 1;

-- 2차가 어느 1차에서 이어졌는지. 협의 결과를 [직전 출력] 에 넣어 다시 만들
-- 때 그 직전 것을 가리킨다. 지금은 비워 두고, 2차 재생성이 붙으면 채운다.
ALTER TABLE plans ADD COLUMN IF NOT EXISTS prev_plan_id BIGINT REFERENCES plans(id);
