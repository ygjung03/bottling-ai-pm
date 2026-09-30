-- 2026-09-28 — RLS 를 켜고 필요한 것만 허용한다
--
-- [무엇이 문제였나]
--
-- anon 키로 모든 테이블의 읽기·수정·삭제가 다 됐다 (9/28 확인. 없는 id 를 조건으로 걸어
-- 권한만 재 봤고 데이터는 건드리지 않았다).
--
--   테이블              읽기   수정   삭제
--   partners           허용   허용   허용
--   plans              허용   허용   허용
--   beers              허용   허용   허용
--   market_context     허용   허용   허용
--   events             허용   허용   허용
--
-- anon 키는 원래 **공개용으로 설계된 키**다. 브라우저 자바스크립트에 넣으라고 만든
-- 것이고 그 자체는 아무 권한도 주지 않는다. 권한을 정하는 것은 RLS 정책이다.
-- 그래서 「anon 을 쓴다」는 맞았지만 「RLS 를 함께 건다」가 빠져 있었다.
--
-- 당장 새고 있지는 않다 — Streamlit 은 서버에서 돌아 키가 브라우저로 나가지 않고,
-- .env 는 gitignore 대상이다. 문제는 그 키가 한 번이라도 새면 DB 전체가 열리는 것이고,
-- 곧 협력사 매입가가 들어온다. 그것을 공개 저장소에 안 넣기로 한 기준(CLAUDE.md 4절)과
-- 어긋난다.
--
-- [service_role 로 바꾸지 않은 이유]
--
-- 우리가 DB 를 부르는 곳이 전부 서버사이드라(Streamlit Cloud · Apps Script ·
-- GitHub Actions) service_role 을 쓰는 것이 정석처럼 보이지만, 넷이 걸린다.
--
--   · 공개 저장소의 GitHub Actions 에 DB 전권 키를 두게 된다
--   · service_role 은 RLS 를 우회한다 — 나중에 정책을 제대로 걸어도 안전망이 안 된다
--   · 키를 넣을 곳이 넷이다 (.env · Cloud Secrets · Apps Script 속성 · Actions Secrets).
--     하나 빠뜨리면 그 경로가 조용히 멈춘다
--   · 새면 피해가 영구적이다. anon 은 정책으로 막을 수 있지만 service_role 은 키를
--     교체해야 하고 그때 또 네 곳을 고친다
--
-- [무엇이 실제로 달라지나]
--
-- 솔직히 이 정책은 「지금 되는 것」을 그대로 허용한다. using (true) 라 조건이 없다.
-- 실질 변화는 **DELETE 차단** 하나다. 그래도 그것이 가장 큰 실익이고, RLS 를 켜 두면
-- 나중에 조건을 좁힐 자리가 생긴다.
--
-- 지금 조건을 좁히지 않는 이유는 좁힐 근거가 없기 때문이다(작업 원칙 ②). 앱에 인증이
-- 아예 없는 것은 아니다 — app/auth.py 가 OWNER_PASSWORD 로 화면을 지킨다. 그래도
-- RLS 조건으로는 쓸 수 없다.
--
--   · 그 인증은 Streamlit 안에서만 돈다. st.session_state 에 플래그를 세우는 방식이고
--     Supabase 는 그것을 모른다. 비밀번호를 맞춰도 DB 로 가는 요청은 같은 anon 키다
--   · 사용자가 한 명이다 — "앱은 대표님만 쓴다"(app/auth.py 주석, 9/17). 「A 는 이 행만,
--     B 는 저 행만」이 성립하려면 사용자가 둘 이상이어야 한다
--   · 초대 코드는 협력사 식별용이고 인증이 아니다
--
-- 그리고 둘이 막는 자리가 다르다.
--
--   앱 화면으로 들어오기   OWNER_PASSWORD 가 막는다        이미 있다
--   키로 DB 직접 부르기   RLS 가 막아야 한다               지금 비어 있다
--
-- 비밀번호는 앱을 지나가는 길만 지킨다. RLS 가 필요한 이유는 앱을 거치지 않고 키로
-- DB 를 직접 부르는 경우이고, 그건 비밀번호를 모르고도 된다.
--
-- [필요한 동작을 코드에서 세어 정했다] (9/28)
--
--   partners        select · insert · update    앱 · 스크립트 · .gs
--   plans           select · insert · update    앱
--   beers           select · insert · update    스크립트
--   events          select · insert · update    앱 · 수집기(upsert)
--   market_context  select · insert · update    앱 · 수집기(upsert)
--   nearby_stores   select · insert · update    앱 · 수집기(upsert)
--   sales_profile   select · insert · update    앱 · 수집기(upsert)
--
-- upsert 는 충돌 시 갱신이라 insert 와 update 가 둘 다 필요하다 (db/client.py:19).
-- .delete() 는 코드 어디에도 없다 — 그래서 어느 테이블에도 delete 를 허용하지 않는다.

alter table partners       enable row level security;
alter table plans          enable row level security;
alter table beers          enable row level security;
alter table events         enable row level security;
alter table market_context enable row level security;
alter table nearby_stores  enable row level security;
alter table sales_profile  enable row level security;

-- ── 읽기 ────────────────────────────────────────────────
create policy "anon read" on partners       for select to anon using (true);
create policy "anon read" on plans          for select to anon using (true);
create policy "anon read" on beers          for select to anon using (true);
create policy "anon read" on events         for select to anon using (true);
create policy "anon read" on market_context for select to anon using (true);
create policy "anon read" on nearby_stores  for select to anon using (true);
create policy "anon read" on sales_profile  for select to anon using (true);

-- ── 넣기 ────────────────────────────────────────────────
-- 협력사 등록 · 기획안 저장 · 수집기 upsert 의 신규 쪽
create policy "anon write" on partners       for insert to anon with check (true);
create policy "anon write" on plans          for insert to anon with check (true);
create policy "anon write" on beers          for insert to anon with check (true);
create policy "anon write" on events         for insert to anon with check (true);
create policy "anon write" on market_context for insert to anon with check (true);
create policy "anon write" on nearby_stores  for insert to anon with check (true);
create policy "anon write" on sales_profile  for insert to anon with check (true);

-- ── 고치기 ──────────────────────────────────────────────
-- 폼 응답 반영(.gs) · 채택 기록 · upsert 의 갱신 쪽
create policy "anon edit" on partners       for update to anon using (true);
create policy "anon edit" on plans          for update to anon using (true);
create policy "anon edit" on beers          for update to anon using (true);
create policy "anon edit" on events         for update to anon using (true);
create policy "anon edit" on market_context for update to anon using (true);
create policy "anon edit" on nearby_stores  for update to anon using (true);
create policy "anon edit" on sales_profile  for update to anon using (true);

-- ── Storage — partner-menus 버킷만 ──────────────────────
-- 버킷은 비공개로 둔다. 구글 드라이브 링크를 공개로 돌리지 않기로 한 것과 같은 이유다
-- (남은_작업 ②-2). 키가 없으면 아무것도 못 본다.
--
-- bucket_id 로 좁혀 두었으므로 다른 버킷을 만들어도 이 정책은 거기에 닿지 않는다.
--
-- Storage 만 delete 를 허용한다 — 정리 스크립트가 사진을 지워야 하고(②-3), 사진은
-- 잃어도 VLM 이 읽은 결과가 menu_prices 에 남는다.
create policy "anon insert partner-menus" on storage.objects
  for insert to anon with check (bucket_id = 'partner-menus');
create policy "anon select partner-menus" on storage.objects
  for select to anon using (bucket_id = 'partner-menus');
create policy "anon delete partner-menus" on storage.objects
  for delete to anon using (bucket_id = 'partner-menus');
