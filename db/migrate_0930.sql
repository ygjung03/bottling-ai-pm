-- 보관함의 「최종 선택」을 DB 에 남긴다 (남은_작업 ㉗)
--
-- 지금은 브라우저 세션에만 있어 새로고침하면 사라진다. 실제 흐름은 1차 제안서를
-- 보내고 며칠 뒤에 폼이 오므로 그 사이에 반드시 끊긴다. 끊기면 「어느 안을
-- 보냈는지」를 사람이 기억해 다시 골라야 하고, 안을 둘 보냈으면 헷갈린다.
--
-- 「담았다」와 「보냈다」는 다른 일이다.
--   adopted_option  마음에 들어 보관함에 담은 안들. 여럿일 수 있다 ("A,C")
--   sent_option     그중 실제로 협력사에 보낸 안 하나. 2차의 메뉴가 된다
--
-- 보내는 일은 화면 밖(메일·카톡)에서 일어나 시스템이 알 수 없다. 그래서 사람이
-- 「최종 선택」을 눌러 알려 준다.

ALTER TABLE plans ADD COLUMN IF NOT EXISTS sent_option TEXT;
COMMENT ON COLUMN plans.sent_option IS
  '협력사에 실제로 보낸 안의 id (예: A). adopted_option 에 담긴 것 중 하나이며, '
  '한 협력사에 하나만 있다. 이 값이 2차의 확정 메뉴를 정한다.';

ALTER TABLE plans ADD COLUMN IF NOT EXISTS sent_at TIMESTAMPTZ;
COMMENT ON COLUMN plans.sent_at IS
  '보낸 안으로 정한 시각. 제안에서 회신까지 며칠 걸렸는지 세는 데 쓴다 (실증 기록).';

-- 「한 협력사에 하나」를 UNIQUE 인덱스로 걸지 않는다.
--
-- 걸면 안을 바꿀 때 옛 행을 비우는 UPDATE 와 새 행을 채우는 UPDATE 사이에서
-- 실패할 수 있고, 그러면 화면이 멈춘다. reply_choice 에 CHECK 를 안 건 것과
-- 같은 이유다 (db/migrate_0928.sql). 코드가 비우고 나서 채운다.
