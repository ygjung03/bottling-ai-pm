# DB 세우는 순서

**정본은 마이그레이션이다.** `schema.sql` 은 9/8 에 만든 최초 스키마이고 그
뒤에 늘어난 칸은 `migrate_*.sql` 에 들어 있다. 둘을 손으로 맞추지 않는다 —
한쪽만 고쳐져 어긋난다.

처음부터 세울 때는 Supabase SQL Editor 에서 아래 순서로 돌린다.

```
1  schema.sql            테이블 8개
2  migrate_*.sql         날짜순으로 전부. 파일 이름이 날짜다
3  rls_0928.sql          RLS 를 켜고 필요한 것만 허용한다
4  grants_1030.sql       Data API 권한
```

3 번과 4 번은 **둘 다 있어야 한다.** 정책은 어느 행을 볼지를 정하고, 권한은
테이블에 닿을 수 있는지를 정한다. 권한이 없으면 행을 고르기도 전에 막힌다.

## 파일

| 파일 | 무엇 |
|---|---|
| `schema.sql` | 최초 스키마 (9/8). 테이블 8개와 그 칸의 뜻 |
| `migrate_0912` ~ `migrate_1015` | 그 뒤에 늘린 칸. 각 파일 머리에 왜 늘렸는지 적혀 있다 |
| `rls_0928.sql` | RLS. anon 에 읽기·등록·수정만, 삭제는 막는다 |
| `grants_1030.sql` | Data API 권한. 2026-10-30 부터 새 테이블은 자동으로 열리지 않는다 |
| `api_usage.py` · `client.py` · `storage.py` | 코드에서 DB 를 부르는 자리 |

## 키

앱은 **anon 키 하나로만** DB 를 부른다. service_role 은 쓰지 않는다 — 공개
저장소의 GitHub Actions 에 전권 키를 두게 되고, RLS 를 우회해 안전망이
사라질 수 있기 때문이다. 자세한 사정은 `rls_0928.sql` 머리에 적어 두었다.

신원 인증은 DB 가 아니라 앱이 한다 (`app/auth.py` 의 `OWNER_PASSWORD`).
Supabase 입장에서는 로그인한 사람이든 아니든 같은 anon 키로 오는 요청이다.