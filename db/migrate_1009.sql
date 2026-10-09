-- 2차 「실행할 안」과 협업 결과 (2026-10-09)
--
-- [왜 필요한가]
--
-- 제안서에 「판매 기간 종료 후 판매량과 손님 반응을 공유하겠다」고 적어 보냈다.
-- 10/9 협업이 끝나면 그 값이 나오는데 넣을 곳이 없다. 보고서의 실증 결과와
-- 다음 협업의 「참고 사례」가 모두 이 값을 쓴다.
--
-- [2차의 「실행할 안」을 따로 두는 이유]
--
-- 1차의 「보낸 안」은 `sent_option` 에 있다 (9/30). 2차도 여러 번 돌려 마음에
-- 드는 것을 담아 둘 수 있고, 그중 실제로 실행하는 것은 하나다. 그 하나를
-- 가리키는 칸이 없었다.
--
-- **`sent_option` 에 섞지 않는다.** 「협력사에 보낸 1차 안」과 「실제로 실행한
-- 2차 안」은 뜻이 다르다. 한 칸에 두면 나중에 어느 뜻인지 매번 따져야 한다.
--
-- 결과 입력 버튼은 **이 값이 있는 줄에만** 뜬다. 1차 줄과 담아만 둔 2차 줄에는
-- 뜨지 않는다 — 실행하지 않은 안에 결과를 적을 일이 없다.
--
-- [실행일을 기간으로 받는 이유]
--
-- 협업은 하루가 아니라 며칠에 걸쳐 한다. 프롬프트 제약에도 「실행 기간은 최소
-- 3일 이상」으로 적혀 있다(`prompts/constraints.yaml:36`). 그런데 `executed_at`
-- 은 날짜 하나짜리라 언제부터 언제까지 했는지 적을 수 없었다.
--
-- `executed_at` 은 스키마와 명세서에만 있고 **읽거나 쓰는 코드가 없었다**
-- (10/9 확인). 그래서 이름을 바꿔 쓴다.

ALTER TABLE plans RENAME COLUMN executed_at TO executed_from;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS executed_to DATE;

-- 2차에서 실제로 실행하기로 고른 안. 한 협력사에 하나다.
ALTER TABLE plans ADD COLUMN IF NOT EXISTS final_option TEXT;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS final_at TIMESTAMPTZ;

COMMENT ON COLUMN plans.executed_from IS
  '실제로 협업을 시작한 날. 전에는 executed_at 이었고 쓰는 코드가 없어 이름을 바꿨다';
COMMENT ON COLUMN plans.executed_to IS
  '실제로 협업을 끝낸 날. 하루만 했으면 executed_from 과 같다';
COMMENT ON COLUMN plans.final_option IS
  '2차에서 실제로 실행하기로 고른 안. 결과 입력 버튼이 이 값이 있는 줄에만 뜬다. 1차의 sent_option 과 뜻이 다르다';
COMMENT ON COLUMN plans.final_at IS
  '그 안을 고른 시각';
