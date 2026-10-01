/**
 * 구글폼 응답 → Supabase partners 연동 (T21)
 *
 * [폼이 둘이다] (2026-09-28)
 *   「협의 사항 입력폼」              모두. 갈래를 정하고 조건을 받는다
 *   「협의 사항 입력폼 (메뉴 확정)」   메뉴를 다시 정한 경우(B/C)만
 *
 *   문항 제목이 같으므로 **이 파일 하나가 두 폼을 모두 처리한다.** 폼마다
 *   응답 시트를 만들고 각 시트에 이 내용을 붙여 트리거를 따로 걸면 된다.
 *
 *   폼 2 의 문항은 폼 1 에도 다 있다. 각 폼은 자기 칸의 최신 응답만 반영하므로
 *   폼 2 를 다시 내도 폼 1 에서 받은 값은 그대로 남는다 (아래 onFormSubmit 참고).
 *
 * [어디에 붙이나]
 *   폼과 연결된 응답 시트를 먼저 만든다 (폼 → 응답 → 스프레드시트에 연결).
 *   그 시트에서 확장 프로그램 → Apps Script → 이 내용을 붙인다.
 *   좌측 「트리거」 → 트리거 추가
 *     실행할 함수   onFormSubmit
 *     이벤트 소스   스프레드시트에서
 *     이벤트 유형   양식 제출 시
 *     실행할 배포   Head
 *     실패 알림     즉시
 *
 *   「양식 제출 시」가 목록에 없으면 그 스프레드시트가 폼 응답 시트가 아니다.
 *   연결한 뒤에 Apps Script 를 열어 뒀다면 페이지를 새로고침한다.
 *
 * [저장이 안 되면 예외를 던진다]
 *   실패 알림 메일은 스크립트가 예외를 던질 때만 온다. 조용히 끝나면
 *   협력사 응답이 DB 에 안 들어갔는데도 아무도 모른다. 그래서 아래에서
 *   저장 실패는 throw 로 끝낸다. 대신 기록만 남기고 넘어가는 경우와
 *   구분해 둔다 — 못 찾은 문항은 그 항목만 비는 것이라 던지지 않는다.
 *
 * [키를 코드에 적지 않는다]
 *   프로젝트 설정 → 스크립트 속성에 둘을 넣는다.
 *     SUPABASE_URL   https://xxxx.supabase.co
 *     SUPABASE_KEY   프로젝트 anon 키
 *
 *   anon 키를 쓴다. RLS 로 필요한 것만 열어 두었다 — 읽기·넣기·고치기는 되고
 *   테이블 삭제는 안 된다 (db/rls_0928.sql). service_role 을 쓰지 않는 이유는
 *   그 키가 RLS 를 전부 우회하기 때문이다.
 *
 * [문항 제목으로 답을 찾는다]
 *   docs/private/쟁점_2차흐름과_폼_0925.md 2절의 제목과 아래 FIELDS 가 같아야
 *   한다. 제목이 어긋나면 그 항목만 조용히 비어서 들어간다. 그래서 아래에서
 *   못 찾은 제목을 따로 기록에 남긴다.
 *
 *   2026-09-28 에 두 폼의 응답 시트 1행을 문서와 글자 단위로 대조했다.
 *   폼 1 은 16/16, 폼 2 는 8/8 일치한다.
 *
 * [어느 협력사인지는 확인 코드로 찾는다]
 *   partners.invite_code 와 맞춘다. 코드가 없거나 맞는 행이 없으면
 *   아무것도 쓰지 않는다. 엉뚱한 협력사 정보를 덮어쓰면 안 된다.
 *
 * [사진은 Supabase Storage 로 옮긴다]
 *   구글 폼에 올린 파일은 폼 소유자 드라이브에 들어가는데, 그 링크로는 우리 앱이
 *   사진을 받을 수 없다 — 인증 없이 열면 구글 로그인 화면이 온다(9/28 확인).
 *   앱은 Streamlit Cloud 에서 도는 파이썬 코드라 구글 계정이 없다.
 *
 *   드라이브 파일 권한을 「링크가 있는 모든 사용자」로 푸는 길도 있지만, 협력사가
 *   준 자료를 공개로 돌리는 것이라 택하지 않았다. 대신 여기서 우리 저장소로
 *   올리고 그 경로를 partners.menu_photo_url 에 남긴다 (남은_작업 ②-2).
 */

// ── 문항 제목 ───────────────────────────────────────────────
// [일치필요] 폼에 적힌 것과 글자 하나까지 같아야 한다.
var FIELDS = {
  code:        '확인 코드는 무엇인가요?',
  reply:       '제안받은 메뉴로 진행하시겠어요?',

  // 메뉴가 정해진 뒤 묻는 것. 폼 1 섹션 2·3 과 폼 2 가 같은 문항을 쓴다.
  //
  // 「이 메뉴」·「그 메뉴」를 「협업 메뉴」로 바꿨다 (10/1). A 갈래는 섹션 2 를
  // 건너뛰어 「그 메뉴」가 무엇인지 앞에 안 나왔다. 폼 1·2 를 함께 바꿨다.
  agreedMenu:  '어떤 메뉴로 협업을 진행하실건가요?',
  salePrice:   '협업 메뉴는 손님에게 얼마에 파시나요?',
  buyPrice:    '협업 메뉴는 개당 얼마에 주실 수 있나요?',
  supplyQty:   '하루에 몇 개씩 주실 수 있나요?',
  storage:     '어떻게 보관하고 며칠 안에 팔아야 하나요?',
  takeout:     '협업 메뉴는 포장 판매가 가능한가요?',
  blockers:    '지켜야 할 조건이 있으면 알려주세요.',

  // 손님에게 어떻게 낼지. 폼 1 섹션 2 에만 있다 (A2 전용).
  // A 는 보낸 안에, B/C 는 고른 안에 들어 있어 화면이 안다.
  approach:    '협의해서 정한 판매 방식은 무엇인가요?',

  // 메뉴를 다시 정하는 경우 (B/C). 폼 1 섹션 4 에만 있다.
  photo:       '메뉴판 사진을 올려주세요.',
  menuNote:    '사진을 올리기 어려우시면 파시는 메뉴중 협업하면 괜찮겠다 하는 메뉴 몇개를 적어주세요.',
  takeoutNote: '포장해서 팔기 어려운 메뉴가 있으면 알려주세요.',

  // 메뉴와 무관한 것. 폼 1 섹션 5·6.
  slots:       '납품은 어느 요일 어느 시간에 가능하신가요?',
  contact:     '전화나 방문으로 이야기 나누기 편한 때는 언제인가요?',
  sns:         '주로 쓰시는 SNS 는 어떤것인가요?',
  content:     '그 채널에 주로 올리시는 것은 무엇인가요?'
};

// 「제안받은 메뉴로 진행하시겠어요?」의 답 → 갈래 코드.
// 갈래별로 2차를 어떻게 만드는지는 쟁점 문서 1-3 에 있다.
var REPLY_CODES = {
  '네, 그 메뉴로 진행하겠습니다.': 'A',
  '협의하여 정한 다른 메뉴가 있습니다.': 'A2',
  '메뉴를 전체 메뉴 중에서 다시 추천받고 싶습니다.': 'B',
  '제안받은 메뉴는 빼고 전체 메뉴 중에서 다시 추천받고 싶습니다.': 'C'
};

// 사진을 올릴 버킷. 비공개다 — 키가 없으면 아무것도 못 본다.
var BUCKET = 'partner-menus';

/**
 * "2,500" · "2500원" · "약 2500원" → 2500. 숫자가 없으면 null.
 *
 * 숫자 아닌 것을 전부 지우지 않고 **첫 숫자 묶음만** 가져온다.
 * 전부 지우면 「2500~3000」이 25003000 이 된다 — 매입가로 그 값이 들어가면
 * 제안서에 그대로 나간다. 폼에 응답 확인(숫자·초과 0)을 걸어 범위 표기를
 * 막았지만, 여기서도 한 겹 더 둔다 (9/28).
 */
function toNumber(text) {
  if (!text) return null;
  var m = String(text).match(/[0-9][0-9,]*/);
  if (!m) return null;
  var n = parseInt(m[0].replace(/,/g, ''), 10);
  return isNaN(n) ? null : n;
}

/**
 * 응답에서 한 문항의 값을 꺼낸다.
 *
 * missing 에 못 찾은 제목을 모아 둔다. 폼에서 제목을 고쳤을 때
 * 조용히 비어서 저장되는 것을 막기 위한 것이다.
 *
 * 폼 2 처럼 그 문항이 애초에 없는 폼도 이 함수를 지나간다. 그때 missing 에
 * 쌓이는 것은 정상이므로, 기록만 남기고 예외를 던지지 않는다.
 */
function answer(values, title, missing) {
  if (!(title in values)) {
    if (missing) missing.push(title);
    return '';
  }
  var v = values[title];
  if (!v) return '';
  return String(Array.isArray(v) ? v[0] : v).trim();
}

/**
 * 답이 여러 개인 문항의 값을 모두 이어 준다 (파일 업로드).
 *
 * 파일을 여러 장 올리면 한 칸에 쉼표로 이어져 들어온다. answer() 는 배열의
 * 첫 값만 보므로 그 경우를 놓친다.
 */
function answerAll(values, title) {
  if (!(title in values)) return '';
  var v = values[title];
  if (!v) return '';
  return (Array.isArray(v) ? v.join(', ') : String(v)).trim();
}

/**
 * 드라이브 링크·id 문자열에서 파일 id 만 뽑는다.
 *
 * 폼 응답에 들어오는 형태가 여러 가지다.
 *   https://drive.google.com/open?id=FILEID
 *   https://drive.google.com/file/d/FILEID/view?usp=drivesdk
 */
function driveIds(text) {
  var out = [];
  if (!text) return out;
  String(text).split(',').forEach(function (part) {
    var s = part.trim();
    if (!s) return;
    var m = s.match(/[?&]id=([\w-]{20,})/)
         || s.match(/\/file\/d\/([\w-]{20,})/)
         || s.match(/^([\w-]{20,})$/);
    if (m) out.push(m[1]);
  });
  return out;
}

/** content type → 파일 확장자. 모르는 것은 bin 으로 둔다. */
function extOf(contentType) {
  var map = {
    'image/jpeg': 'jpg', 'image/jpg': 'jpg', 'image/png': 'png',
    'image/webp': 'webp', 'image/heic': 'heic', 'image/heif': 'heic',
    'image/gif': 'gif'
  };
  return map[String(contentType).toLowerCase()] || 'bin';
}

/**
 * 드라이브에 올라온 사진을 Supabase Storage 로 옮긴다.
 *
 * 반환: { paths: [...올라간 경로], failed: [...실패 사유] }
 *
 * 실패해도 예외를 던지지 않는다. 폼 값 저장이 먼저이고, 사진 하나 때문에
 * 매입가·조건이 다 날아가면 손해다(작업 원칙 ⑤). 대신 사유를 모아 두고
 * 저장이 끝난 뒤에 알린다.
 *
 * 드라이브의 원본은 지우지 않는다. 옮긴 것이 잘못됐을 때 되돌릴 데가 있어야
 * 하고, 사진 몇 장이라 용량이 문제되지 않는다.
 *
 * [경로에 드라이브 파일 id 를 쓴다]
 *   트리거는 두 번 돌 수 있다 — 응답을 수정해 다시 내거나, 스크립트를 고쳐
 *   같은 응답을 다시 돌릴 때다. 경로에 시각을 넣으면 그때마다 새 파일이 생기고
 *   menu_photo_url 은 새 경로로 덮이면서 **옛 파일만 버킷에 쓰레기로 남는다.**
 *
 *   파일 id 는 그 사진의 고유값이라 같은 사진이면 같은 경로가 된다.
 *   x-upsert 로 덮어쓰므로 몇 번을 돌려도 쌓이지 않는다.
 *
 *   버킷이 비공개라 id 가 경로에 드러나도 상관없고, 어느 드라이브 파일에서
 *   왔는지 되짚을 수 있어 오히려 낫다.
 */
function movePhotos(text, code, url, key) {
  var ids = driveIds(text);
  var paths = [];
  var failed = [];
  if (!ids.length) return { paths: paths, failed: failed };

  ids.forEach(function (id) {
    try {
      var blob = DriveApp.getFileById(id).getBlob();
      var ctype = blob.getContentType();
      var path = code + '/' + id + '.' + extOf(ctype);

      var res = UrlFetchApp.fetch(
        url + '/storage/v1/object/' + BUCKET + '/' + encodeURIComponent(path),
        {
          method: 'post',
          contentType: ctype,
          headers: {
            apikey: key,
            Authorization: 'Bearer ' + key,
            'x-upsert': 'true'      // 같은 사진을 다시 올리면 덮는다
          },
          payload: blob.getBytes(),
          muteHttpExceptions: true
        });

      var status = res.getResponseCode();
      if (status >= 200 && status < 300) {
        paths.push(path);
      } else {
        failed.push(id + ' → HTTP ' + status + ' ' + res.getContentText());
      }
    } catch (err) {
      failed.push(id + ' → ' + err);
    }
  });

  return { paths: paths, failed: failed };
}

/**
 * [이미 제출된 응답을 다시 돌리려면]
 *
 * 트리거는 앞으로 들어오는 제출에만 붙는다. 스크립트를 고치거나 속성을 빠뜨려
 * 실패했을 때, 그 응답을 소급해서 처리하지 않는다.
 *
 * 폼 설정 → 「제출 후 수정」을 켜 두면 제출 완료 화면에 수정 링크가 나온다.
 * **그 링크를 적어 두고** 그것으로 다시 제출한다.
 *
 *   「제출 후 수정」은 사후에 켜도 이미 낸 응답에는 링크가 안 생긴다. 켠 뒤에
 *   낸 것부터 적용된다. 그리고 응답 시트에는 수정 URL 열이 없어 링크를 잃으면
 *   다시 얻기 어렵다.
 *
 * 시트의 마지막 행을 읽어 onFormSubmit 을 직접 부르는 함수를 두었다가 뺐다
 * (9/28). 둘이 걸려서다.
 *   · SpreadsheetApp 읽기 권한이 새로 필요하다 — onFormSubmit 은 시트를 안 읽는다
 *   · 시트에 응답이 여러 개 쌓이면 「마지막 행」이 누구 것인지 모른 채 실행해
 *     엉뚱한 협력사를 덮을 수 있다. 같은 값으로 덮으니 망가지지는 않지만
 *     updated_at 이 바뀌어 「마지막 제출 시점」 기록이 틀려진다
 *
 * 수정 제출이 트리거를 다시 돌리지 않는 것으로 확인되면 그 함수를 다시 쓴다.
 * 그때는 한 번만 쓰고 빼는 편이 낫다.
 */

/**
 * 지금 DB 에 적힌 갈래. 없거나 못 읽으면 null.
 *
 * 폼 1 을 다시 냈을 때 갈래가 바뀌었는지 보려고 읽는다. 바뀌었으면 폼 2 가
 * 채운 값이 옛 갈래의 것이라 무효가 된다.
 */
function currentReply(url, key, code) {
  try {
    var res = UrlFetchApp.fetch(
      url + '/rest/v1/partners?invite_code=eq.' + encodeURIComponent(code)
          + '&select=reply_choice',
      {
        method: 'get',
        headers: { apikey: key, Authorization: 'Bearer ' + key },
        muteHttpExceptions: true
      });
    if (res.getResponseCode() >= 300) return null;
    var rows = JSON.parse(res.getContentText() || '[]');
    return rows.length ? rows[0].reply_choice : null;
  } catch (err) {
    Logger.log('이전 갈래를 읽지 못했다: ' + err);
    return null;
  }
}

function onFormSubmit(e) {
  var values = e && e.namedValues;
  if (!values) {
    throw new Error('응답이 비어 있다. 트리거의 이벤트 유형이 '
                    + '「양식 제출 시」인지 확인할 것.');
  }

  var missing = [];
  var code = answer(values, FIELDS.code, missing);
  if (!code) {
    throw new Error('확인 코드가 없다. 미리 채운 링크로 보냈는지, '
                    + '협력사가 그 칸을 지우지 않았는지 확인할 것.');
  }

  var props = PropertiesService.getScriptProperties();
  var url = props.getProperty('SUPABASE_URL');
  var key = props.getProperty('SUPABASE_KEY');
  if (!url || !key) {
    throw new Error('스크립트 속성에 SUPABASE_URL / SUPABASE_KEY 가 없다.');
  }

  // 「지켜야 할 조건」은 한 줄에 하나씩 적게 한다. 「없음」이라고 적힌 경우는
  // 여기서 걸러내지 않는다 — 「아직 안 냈다」와 「없다고 확인해 줬다」를
  // 구분해야 하고 그 판단은 chain/inputs.py 의 NO_BLOCKER 가 한다.
  var blockers = answer(values, FIELDS.blockers, missing)
    .split('\n')
    .map(function (s) { return s.trim(); })
    .filter(function (s) { return s.length > 0; });

  // 갈래. 선택지 문장을 코드로 바꾼다. 못 알아본 답은 원문을 그대로 넣고
  // 크게 기록한다 — 값을 버리면 복구할 데가 없다. 화면이 넷 중 하나가
  // 아닌 값을 잡는다 (db/migrate_0928.sql 의 reply_choice 주석).
  var replyText = answer(values, FIELDS.reply, missing);
  var reply = '';
  if (replyText) {
    reply = REPLY_CODES[replyText] || '';
    if (!reply) {
      reply = replyText;
      Logger.log('갈래를 못 알아봤다: "' + replyText + '"'
                 + '  → 폼 선택지 문구가 바뀌었는지 확인할 것 (REPLY_CODES)');
    }
  }

  // 사진을 우리 저장소로 옮긴다. 폼 2 에는 이 문항이 없어 빈 결과가 온다.
  var photos = movePhotos(answerAll(values, FIELDS.photo), code, url, key);

  var payload = {
    reply_choice:      reply,
    agreed_menu:       answer(values, FIELDS.agreedMenu, missing),
    agreed_sale_price: toNumber(answer(values, FIELDS.salePrice, missing)),
    agreed_price:      toNumber(answer(values, FIELDS.buyPrice, missing)),
    // 선택지 문장을 그대로 넣는다. 「단품」·「세트」·「포장」으로 바꾸는 일은
    // 화면이 한다 — 「아직 정하지 않았습니다」와 기타 서술형도 와서, 여기서
    // 셋 중 하나로 줄이면 그 답이 사라진다.
    agreed_approach:   answer(values, FIELDS.approach, missing),
    supply_qty:        answer(values, FIELDS.supplyQty, missing),
    storage_note:      answer(values, FIELDS.storage, missing),
    takeout:           answer(values, FIELDS.takeout, missing),
    takeout_note:      answer(values, FIELDS.takeoutNote, missing),
    menu_note:         answer(values, FIELDS.menuNote, missing),
    menu_photo_url:    photos.paths,

    available_slots:   answer(values, FIELDS.slots, missing),
    contact_slots:     answer(values, FIELDS.contact, missing),
    sns_channel:       answer(values, FIELDS.sns, missing),
    sns_content_type:  answer(values, FIELDS.content, missing),
    blockers:          blockers,

    // 협력사가 언제 제출했는지. partners.updated_at 은 DEFAULT now() 뿐이라
    // 갱신 시 자동으로 바뀌지 않는다. 안 넣으면 행을 처음 만든 날짜가
    // 그대로 남아 마지막 제출 시점을 알 수 없다.
    updated_at:        new Date().toISOString()
  };

  if (missing.length) {
    Logger.log('이 폼에 없는 문항: ' + missing.join(' / ')
               + '  → 폼 2 라면 정상이다. 폼 1 이라면 제목이 바뀌었는지 확인할 것'
               + ' (docs/private/쟁점_2차흐름과_폼_0925.md 2절)');
  }

  // 각 폼이 받은 가장 최신 응답이 반영되도록 한다.
  //
  //   폼 2 를 다시 내면    폼 2 응답만 바꾸고 폼 1 응답은 그대로 둔다
  //   폼 1 을 다시 내면    폼 1 응답을 이번 답으로 바꾼다. 안 적은 응답은 비운다
  //   폼 1 을 다시 내면서 메뉴 갈래가 바뀌면
  //                        폼 2 응답을 비운다. 지난 갈래의 답이라 쓸 수 없다
  //
  // SHARED 가 폼 2 의 칸이다. 폼 2 문항은 폼 1 에도 다 있다.
  var SHARED = ['agreed_menu', 'agreed_sale_price', 'agreed_price',
                'supply_qty', 'storage_note', 'takeout', 'blockers'];
  var SOURCE = {
    reply_choice: FIELDS.reply, agreed_menu: FIELDS.agreedMenu,
    agreed_approach: FIELDS.approach, agreed_sale_price: FIELDS.salePrice,
    agreed_price: FIELDS.buyPrice, supply_qty: FIELDS.supplyQty,
    storage_note: FIELDS.storage, takeout: FIELDS.takeout,
    blockers: FIELDS.blockers, menu_photo_url: FIELDS.photo,
    menu_note: FIELDS.menuNote, takeout_note: FIELDS.takeoutNote,
    available_slots: FIELDS.slots, contact_slots: FIELDS.contact,
    sns_channel: FIELDS.sns, sns_content_type: FIELDS.content
  };
  var EMPTY = { blockers: [], menu_photo_url: [] };   // NOT NULL 배열 칸

  var prevReply = currentReply(url, key, code);
  var switched = !!(reply && prevReply && reply !== prevReply);

  Object.keys(payload).forEach(function (k) {
    if (!(k in SOURCE)) return;                                  // updated_at
    if (!(SOURCE[k] in values)) { delete payload[k]; return; }   // 이 폼에 없는 문항
    var v = payload[k];
    if (v !== '' && v !== null && !(Array.isArray(v) && !v.length)) return;
    if (SHARED.indexOf(k) >= 0 && !switched) { delete payload[k]; return; }
    payload[k] = (k in EMPTY) ? EMPTY[k] : null;
  });

  var res = UrlFetchApp.fetch(
    url + '/rest/v1/partners?invite_code=eq.' + encodeURIComponent(code),
    {
      method: 'patch',
      contentType: 'application/json',
      headers: {
        apikey: key,
        Authorization: 'Bearer ' + key,
        Prefer: 'return=representation'
      },
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });

  var status = res.getResponseCode();
  var body = res.getContentText();

  if (status < 200 || status >= 300) {
    throw new Error('저장 실패 ' + status + ' — ' + body);
  }
  if (body === '[]') {
    // 200 인데 빈 배열이면 그 코드에 맞는 협력사가 없다는 뜻이다.
    throw new Error('확인 코드 "' + code + '" 에 맞는 협력사가 없다. '
                    + '아무것도 쓰이지 않았다.');
  }

  Logger.log('저장 완료 — 갈래 ' + (reply || '(없음)')
             + ', 사진 ' + photos.paths.length + '장'
             + ', 불가 조건 ' + blockers.length + '개'
             + ', 채운 항목 ' + Object.keys(payload).length + '개');

  // 폼 값은 저장됐지만 사진이 하나라도 실패하면 알린다. 알림 메일은 예외를
  // 던질 때만 오므로 여기서 던진다 — 저장은 끝난 뒤라 값이 날아가지 않는다.
  if (photos.failed.length) {
    throw new Error('폼 값은 저장됐다. 다만 사진 '
                    + photos.failed.length + '장을 옮기지 못했다: '
                    + photos.failed.join(' / '));
  }
}