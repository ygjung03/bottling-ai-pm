-- 2026-10-30 — Data API 권한을 명시한다
--
-- [무엇이 바뀌었나]
--
-- Supabase 가 2026-10-30 부터 public 스키마의 **새 테이블**에 Data API 권한을
-- 자동으로 주지 않는다. 지금 돌고 있는 프로젝트는 이미 받은 권한을 그대로
-- 가지고 있어 영향이 없다.
--
-- 걸리는 것은 **처음부터 다시 세울 때**다. 새 Supabase 프로젝트나 로컬
-- 재생성에서는 권한이 없어 앱이 「permission denied」 로 멈춘다. 공개
-- 저장소라 남이 받아서 해볼 수도 있는데 그때 문제가 생길 수 있다. 
--
-- [RLS 와 다른 것이다]
--
-- db/rls_0928.sql 의 정책은 **어느 행을 볼지**를 정하고, 여기 grant 는
-- **테이블에 닿을 수 있는지**를 정한다. 둘 다 있어야 돌아간다. 정책만 있고
-- 권한이 없으면 행을 고르기도 전에 막힌다.
--
-- [anon 에만 준다]
--
-- DB 를 부르는 곳이 전부 anon 키 하나다. service_role 을 쓰지 않기로 한
-- 이유는 rls_0928.sql 에 적어 두었다 — 공개 저장소의 GitHub Actions 에 전권
-- 키를 두게 되고, RLS 를 우회해 안전망이 사라진다.
-- Supabase 로그인을 쓰지 않으므로 authenticated 에도 주지 않는다.
--
-- [delete 는 빼 둔다]
--
-- rls_0928.sql 이 delete 정책을 두지 않은 것과 같은 뜻이다. 지우는 일은
-- Supabase 콘솔에서 사람이 한다.
--
-- 이미 권한이 있는 프로젝트에서 다시 돌려도 안전하다.

GRANT USAGE ON SCHEMA public TO anon;

GRANT SELECT, INSERT, UPDATE ON
  partners,
  beers,
  market_context,
  sales_profile,
  nearby_stores,
  events,
  plans,
  api_usage
TO anon;

-- id 가 BIGSERIAL 이라 INSERT 에는 시퀀스 권한이 함께 있어야 한다.
-- 없으면 읽기는 되는데 등록만 「permission denied」 로 막힌다.
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO anon;