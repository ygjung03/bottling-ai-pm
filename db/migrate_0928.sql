-- 2026-09-28 — 협의 결과를 받는 컬럼 (구글 폼 재구성)
--
-- 폼이 둘로 나뉘고 문항이 새로 짜였다. 협력사가 아니라 바틀링 대표님이 협의 자리에서
-- 채운다 (docs/private/쟁점_2차흐름과_폼_0925.md 2절).
--
--   「협의 사항 입력폼」              모두. 갈래를 정하고 조건을 받는다
--   「협의 사항 입력폼 (메뉴 확정)」   메뉴를 다시 정한 경우(B/C)만
--
-- 아래 컬럼은 전부 **협의 결과**다. 1차 기획안은 이 값 없이 만들고(후기·사진에서 본
-- 값으로 추정), 2차는 이 값으로 확정한다. 그래서 전부 NULL 허용이다 — 폼이 오기 전에는
-- 비어 있는 것이 정상이고, 비었다는 사실 자체가 「아직 협의 전」이라는 뜻이다.
--
-- 기존 컬럼과 겹치는 이름은 없다 (schema.sql 9~36행과 대조).

-- ── 갈래 ──────────────────────────────────────────────
-- 「제안받은 메뉴로 진행하시겠어요?」의 답을 .gs 가 코드로 바꿔 넣는다.
--
--   A   네, 그 메뉴로 진행하겠습니다.
--   A2  협의하여 정한 다른 메뉴가 있습니다.
--   B   메뉴를 전체 메뉴 중에서 다시 추천받고 싶습니다.
--   C   제안받은 메뉴는 빼고 전체 메뉴 중에서 다시 추천받고 싶습니다.
--
-- CHECK 제약을 걸지 않는다. 걸면 매핑이 어긋났을 때 PATCH 전체가 실패해 폼 값이 하나도
-- 저장되지 않는다 — 제출은 됐는데 DB 에 없는 상태가 가장 나쁘다. 대신 값이 넷 중
-- 하나가 아니면 화면에서 잡는다. 원문은 폼 응답 시트에 남아 있어 복구할 수 있다.
ALTER TABLE partners ADD COLUMN IF NOT EXISTS reply_choice TEXT;
COMMENT ON COLUMN partners.reply_choice IS
  '폼에서 고른 갈래 — A(그 메뉴로) / A2(협의로 다른 메뉴) / B(전체에서 재추천) / C(그 메뉴 빼고 재추천)';

-- ── 확정된 협업 메뉴와 그 조건 ──────────────────────────
-- 한 협업에 메뉴는 하나다 (쟁점 1-1-3). 그래서 JSONB 배열이 아니라 단일 값이다.
--
-- A 는 메뉴 이름이 폼에 들어오지 않는다. 제안받은 그 메뉴이므로 2차를 만들 때 고른
-- 1차 안에서 가져온다 (plans.prev_plan_id).
ALTER TABLE partners ADD COLUMN IF NOT EXISTS agreed_menu TEXT;
COMMENT ON COLUMN partners.agreed_menu IS
  '협의로 정한 협업 메뉴 하나. A2 는 폼 1, B/C 는 폼 2 에서 온다. A 는 비고 1차 안에서 가져온다';

ALTER TABLE partners ADD COLUMN IF NOT EXISTS agreed_sale_price INTEGER;
COMMENT ON COLUMN partners.agreed_sale_price IS
  '그 메뉴를 협력사가 손님에게 받는 값(원). menu_prices 의 추정 판매가와 달리 협의로 확인한 값';

-- 협의로 정해진 매입가다. (4)가 제안하는 값이 아니라 **협력사가 폼에 적은 값**이다.
-- 그래서 2차에서는 AI 가 매입가를 다시 제안하지 않고 이 값을 쓴다 (쟁점 2절
-- 「매입가를 (2)로 옮긴다」). 100원 단위 규칙은 걸지 않는다 — 그것은 AI 제안값의
-- 규칙이고, 협력사가 2,450원이라고 하면 그것이 사실이다.
ALTER TABLE partners ADD COLUMN IF NOT EXISTS agreed_price INTEGER;
COMMENT ON COLUMN partners.agreed_price IS
  '바틀링이 그 메뉴를 개당 사 오는 값(원). 협의로 정한 확정값. AI 제안값이 아니다';

-- 「하루에 몇 개씩 주실 수 있나요?」
-- 숫자가 아니라 TEXT 다. 「하루 20개, 미리 말씀하시면 30개까지」처럼 여유까지 함께
-- 적게 하기 때문이다. 「만들 수 있는 최대」가 아니라 「이번 협업에 주실 수 있는 양」을
-- 묻는다 — 최대 생산량만 알면 그만큼 팔 수 있다고 잘못 계산한다 (쟁점 2절).
ALTER TABLE partners ADD COLUMN IF NOT EXISTS supply_qty TEXT;
COMMENT ON COLUMN partners.supply_qty IS
  '이번 협업에 하루 납품 가능한 수량. 여유를 함께 적으므로 TEXT (예: 하루 20개, 미리 말씀하시면 30개까지)';

ALTER TABLE partners ADD COLUMN IF NOT EXISTS storage_note TEXT;
COMMENT ON COLUMN partners.storage_note IS
  '보관 방법과 며칠 안에 팔아야 하는지 (예: 실온 보관, 당일 안에)';

-- 값이 둘뿐이다 — 「가능합니다.」/「어렵습니다.」. 메뉴가 하나로 정해진 뒤의 답이라
-- 「메뉴에 따라 다릅니다」가 성립하지 않는다.
-- 폼의 답을 그대로 담는다. BOOLEAN 으로 바꾸지 않는 이유는 매핑을 한 겹 줄여
-- .gs 가 조용히 틀릴 자리를 없애기 위해서다.
--
-- **마침표가 붙는다.** 폼 선택지가 「가능합니다.」 「어렵습니다.」로 되어 있고 실제
-- 제출로 확인했다(9/28). 코드에서 판정할 때 == '가능합니다' 로 비교하면 어긋난다.
ALTER TABLE partners ADD COLUMN IF NOT EXISTS takeout TEXT;
COMMENT ON COLUMN partners.takeout IS
  '확정된 메뉴를 포장해서 팔 수 있나 — 폼의 답 그대로 (가능합니다. / 어렵습니다.)';

-- (B/C 폼 1) 「포장해서 팔기 어려운 메뉴가 있으면 알려주세요」
-- 제외 조건이 아니다. 그 메뉴가 추천에서 빠지는 것이 아니라, 뽑혔을 때 매장에서
-- 드시는 안으로만 기획한다.
ALTER TABLE partners ADD COLUMN IF NOT EXISTS takeout_note TEXT;
COMMENT ON COLUMN partners.takeout_note IS
  '(B/C) 포장이 어려운 메뉴. 추천에서 빼는 조건이 아니라 참고사항이다';

-- ── 전체 메뉴를 받는 두 경로 (B/C) ──────────────────────
-- 사진이 우선이고, 없을 때 이름만 받는다. 사진 문항을 필수로 잠그지 않은 이유는
-- 제출이 막히면 대표님이 B/C 를 못 고르고 다른 답을 고르게 되기 때문이다 (쟁점 2절).
ALTER TABLE partners ADD COLUMN IF NOT EXISTS menu_photo_url TEXT[]
  NOT NULL DEFAULT '{}';
COMMENT ON COLUMN partners.menu_photo_url IS
  '(B/C) 메뉴판·POS·배달앱 사진. VLM 으로 읽어 menu_prices 를 교체한다';

ALTER TABLE partners ADD COLUMN IF NOT EXISTS menu_note TEXT;
COMMENT ON COLUMN partners.menu_note IS
  '(B/C) 사진 대신 적어 주신 메뉴 이름. 쉼표로 구분된 그대로';

-- ── 확실한 메뉴와 추측한 메뉴를 나눈다 ──────────────────
-- 지금까지 menu_prices 하나에 다 담으려 했다. 그런데 들어오는 경로의 신뢰도가 다르다.
--
--   확실  수동 등록 (대표님이 직접 넣은 값) · 메뉴판 사진 → VLM
--   추측  네이버 블로그 후기에서 모은 것 (U17)
--
-- **후기는 시점이 과거다.** 「후기 5건, 2026-08」은 8월에 누가 그 메뉴를 언급했다는
-- 뜻이지 지금 판다는 뜻이 아니다. 지금 안 파는 메뉴가 협업 후보로 들어간다.
--
-- 한 컬럼에 섞어 담고 「근거」 문자열로 걸러낼 수도 있지만 컬럼을 나눈다. 
-- 「사진이 들어오면 후기 값을 버린다」가 되돌릴 수 없는 동작이기 때문이다 — 사진을
-- 잘못 읽었을 때 후기 값까지 없어진다. 나눠 두면 지우지 않고 무시한다.
--
-- chain/inputs.py 의 _menus() 우선순위가 한 줄이 된다.
--   rows = partner.get("menu_prices") or partner.get("menu_prices_review") or []
-- 확실한 값이 있으면 후기는 프롬프트에 아예 싣지 않는다.
ALTER TABLE partners ADD COLUMN IF NOT EXISTS menu_prices_review JSONB
  NOT NULL DEFAULT '[]';
COMMENT ON COLUMN partners.menu_prices_review IS
  '블로그 후기에서 모은 메뉴·가격 (U17). menu_prices 가 비었을 때만 쓴다 — 후기는 시점이 과거다';

-- 「근거」 칸은 양쪽 다 쓴다. 컬럼 추가가 아니라 JSONB 항목에 이미 있는 칸인데
-- schema.sql 주석에 빠져 있었다. chain/inputs.py:361 이 읽어 판매가 뒤에 괄호로 싣는다.
--
-- menu_prices 안에서도 신뢰도가 갈린다 — 「메뉴판 사진」이 「수동 등록」보다 최신이고
-- 전체를 담는다. 사진이 들어오면 menu_prices 를 교체한다(합치지 않는다). 수동으로
-- 3개를 넣었는데 사진에 12개가 있으면 12개가 맞다. 사진에 안 찍힌 것은 화면의 메뉴
-- 표에서 대표님이 더한다.
COMMENT ON COLUMN partners.menu_prices IS
  '확실한 메뉴와 가격 — 수동 등록 또는 메뉴판 사진. [{"메뉴":..,"가격":..,"납품가":..,"근거":"메뉴판 사진 (2026-09-28)"}]';

-- ── 폼에서 빠진 문항의 컬럼 ────────────────────────────
-- 「그중 대표 메뉴」 문항을 뺐다. 어느 경로로도 채워지지 않는다 — .gs 가 폼에 없으면
-- 첫 메뉴를 넣던 대체 경로도 메뉴 1~5 문항과 함께 없어졌다.
--
-- menu_prices 에 메뉴가 다 있으므로 따로 둘 이유가 없다. 지금 값도 menu_prices 와
-- 중복이다. 읽던 두 곳을 정리한다.
--   chain/inputs.py:400   쪽지의 「- 대표 메뉴:」 줄 → 뺀다
--   chain/checks.py:517   재료 출처 → agreed_menu 로 교체한다
--
-- 컬럼은 지금 지우지 않는다. equipment 와 함께 다음 정리에서 지운다 — 남겨도 비용이
-- 없고 지우는 것은 되돌릴 수 없다.
COMMENT ON COLUMN partners.signature_menu IS
  '[미사용] 폼에서 「그중 대표 메뉴」를 뺐다(9/28). menu_prices 와 중복이다. 다음 정리에서 지운다';

-- ── 이미 들어 있는 후기 값을 옮긴다 ─────────────────────
-- 컬럼을 나누기 전에 넣은 값이 menu_prices 에 섞여 있다. 옮기지 않으면 컬럼을 나눈
-- 뜻이 없어진다 — 코드는 menu_prices 를 「확실한 값」으로 읽는데 그 안에 후기가 있다.
--
-- 옮길 때 확인한 것 (9/28, 읽기 전용 조회):
--   프레즐          메뉴 32개, 전부 근거 「블로그 후기, 2026-09-19 확인」  → 옮긴다
--   테스트용 제과점  메뉴 3개, 근거 없음 (손으로 넣은 값)                  → 남긴다
--   나머지 4곳      메뉴 없음
--
-- 근거가 비어 있는 항목은 남긴다. 출처를 모르면 지어내지 않는다(작업 원칙 ③) —
-- 「수동 등록」이라고 채워 넣으면 확인하지 않은 것을 사실로 적는 셈이다.
--
-- 두 번 실행해도 안전하다. 옮긴 뒤에는 menu_prices 에 후기 항목이 없어 WHERE 가
-- 걸러낸다.
UPDATE partners
SET menu_prices_review = (
      SELECT COALESCE(jsonb_agg(e), '[]'::jsonb)
      FROM jsonb_array_elements(menu_prices) e
      WHERE e->>'근거' LIKE '%후기%'
    ),
    menu_prices = (
      SELECT COALESCE(jsonb_agg(e), '[]'::jsonb)
      FROM jsonb_array_elements(menu_prices) e
      WHERE e->>'근거' IS NULL OR e->>'근거' NOT LIKE '%후기%'
    )
WHERE jsonb_typeof(menu_prices) = 'array'
  AND EXISTS (
      SELECT 1 FROM jsonb_array_elements(menu_prices) e
      WHERE e->>'근거' LIKE '%후기%'
  );
