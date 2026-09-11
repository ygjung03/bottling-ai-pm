/**
 * 구글폼 응답 → Supabase partners 연동 (T21)
 *
 * [어디에 붙이나]
 *   폼과 연결된 응답 시트를 먼저 만든다 (폼 → 응답 → 스프레드시트에 연결).
 *   그 시트에서 확장 프로그램 → Apps Script → 이 내용을 붙인다.
 *   좌측 「트리거」 → 트리거 추가
 *     실행할 함수   onFormSubmit
 *     이벤트 소스   스프레드시트에서
 *     이벤트 유형   양식 제출 시
 *
 * [키를 코드에 적지 않는다]
 *   프로젝트 설정 → 스크립트 속성에 둘을 넣는다.
 *     SUPABASE_URL   https://xxxx.supabase.co
 *     SUPABASE_KEY   프로젝트 API 키
 *
 * [문항 제목으로 답을 찾는다]
 *   docs/협력사_구글폼_문항.md 의 제목과 아래 FIELDS 가 같아야 한다.
 *   제목이 어긋나면 그 항목만 조용히 비어서 들어간다. 그래서 아래에서
 *   못 찾은 제목을 따로 기록에 남긴다.
 *
 * [어느 협력사인지는 확인 코드로 찾는다]
 *   partners.invite_code 와 맞춘다. 코드가 없거나 맞는 행이 없으면
 *   아무것도 쓰지 않는다. 엉뚱한 협력사 정보를 덮어쓰면 안 된다.
 */

var FIELDS = {
  code:      '확인 코드',
  name:      '가게 이름',
  category:  '업종',
  signature: '그중 대표 메뉴',
  slots:     '협업 가능 일정',
  sns:       'SNS 채널',
  followers: '팔로워 수',
  content:   '주로 올리시는 것',
  blockers:  '이것만은 안 된다는 것'
};

var MENU_COUNT = 5;

/** "3,000" · "3000원" → 3000. 숫자가 없으면 null. */
function toNumber(text) {
  if (!text) return null;
  var digits = String(text).replace(/[^0-9]/g, '');
  return digits ? parseInt(digits, 10) : null;
}

/**
 * 응답에서 한 문항의 값을 꺼낸다.
 *
 * missing 에 못 찾은 제목을 모아 둔다. 폼에서 제목을 고쳤을 때
 * 조용히 비어서 저장되는 것을 막기 위한 것이다.
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
 * 메뉴 1~5 를 [{메뉴, 가격, 납품가}] 으로 모은다.
 *
 * 메뉴명이 없는 줄은 버린다. 납품가는 선택 항목이라 비어 있으면 null 이고,
 * 그 메뉴의 매입가는 협의로 정해진다.
 */
function collectMenus(values) {
  var out = [];
  for (var i = 1; i <= MENU_COUNT; i++) {
    var name = answer(values, '메뉴 ' + i);
    if (!name) continue;
    out.push({
      '메뉴': name,
      '가격': toNumber(answer(values, '메뉴 ' + i + ' 가격')),
      '납품가': toNumber(answer(values, '메뉴 ' + i + ' 납품가'))
    });
  }
  return out;
}

function onFormSubmit(e) {
  var values = e && e.namedValues;
  if (!values) {
    Logger.log('응답이 비어 있다. 트리거를 「스프레드시트에서 / 양식 제출 시」로 걸었는지 확인할 것.');
    return;
  }

  var missing = [];
  var code = answer(values, FIELDS.code, missing);
  if (!code) {
    Logger.log('확인 코드가 없다. 미리 채운 링크로 보냈는지 확인할 것.');
    return;
  }

  var menus = collectMenus(values);
  var blockers = answer(values, FIELDS.blockers, missing)
    .split('\n')
    .map(function (s) { return s.trim(); })
    .filter(function (s) { return s.length > 0; });

  var payload = {
    name:             answer(values, FIELDS.name, missing),
    category:         answer(values, FIELDS.category, missing),
    menu_prices:      menus,
    signature_menu:   answer(values, FIELDS.signature, missing)
                      || (menus.length ? menus[0]['메뉴'] : null),
    available_slots:  answer(values, FIELDS.slots, missing),
    sns_channel:      answer(values, FIELDS.sns, missing) || null,
    sns_followers:    toNumber(answer(values, FIELDS.followers, missing)),
    sns_content_type: answer(values, FIELDS.content, missing) || null,
    blockers:         blockers
  };

  if (missing.length) {
    Logger.log('폼에서 못 찾은 문항: ' + missing.join(' / ')
               + '  → 제목이 바뀌었는지 확인할 것 (docs/협력사_구글폼_문항.md)');
  }

  // 빈 값으로 기존 내용을 지우지 않는다. 협력사가 일부만 고쳐 다시 냈을 때
  // 안 적은 항목까지 날아가면 이전 답을 잃는다.
  Object.keys(payload).forEach(function (k) {
    var v = payload[k];
    if (v === '' || v === null || (Array.isArray(v) && !v.length)) {
      delete payload[k];
    }
  });

  var props = PropertiesService.getScriptProperties();
  var url = props.getProperty('SUPABASE_URL');
  var key = props.getProperty('SUPABASE_KEY');
  if (!url || !key) {
    Logger.log('스크립트 속성에 SUPABASE_URL / SUPABASE_KEY 가 없다.');
    return;
  }

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
    Logger.log('저장 실패 ' + status + ' — ' + body);
    return;
  }
  if (body === '[]') {
    // 200 인데 빈 배열이면 그 코드에 맞는 협력사가 없다는 뜻이다.
    Logger.log('확인 코드 "' + code + '" 에 맞는 협력사가 없다. 아무것도 쓰이지 않았다.');
    return;
  }
  Logger.log('저장 완료 — 메뉴 ' + menus.length + '개, 불가 조건 ' + blockers.length + '개');
}
