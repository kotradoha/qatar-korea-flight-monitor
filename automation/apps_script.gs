/**
 * 카타르항공 도하↔인천 운항 모니터 — 구독자 저장 + 이메일 자동 발송 (Google Apps Script)
 *
 * 이 스크립트 하나가:
 *   1) 웹페이지 구독/취소 신청을 받아 구글 시트에 저장하고
 *   2) GitHub Actions가 알림을 보내오면 구독자 전원에게 이메일을 발송합니다.
 *
 * 발송은 이 스크립트를 소유한 지메일 계정(qatarandkorea@gmail.com 권장)에서 나갑니다.
 * 무료이며, 하루 발송 한도는 계정 유형에 따라 약 100~1,500건입니다.
 *
 * === 최초 설정 ===
 * 1) qatarandkorea@gmail.com 으로 로그인 → https://sheets.new 새 스프레드시트 생성.
 *    첫 시트 이름을 'subscribers'로 바꾸고, 1행에 헤더 입력: time | type | contact
 *    주소창의 .../d/<이 부분이 SHEET_ID>/edit 에서 SHEET_ID 복사.
 * 2) https://script.google.com → 새 프로젝트 → 이 코드 전체 붙여넣기.
 * 3) 아래 SHEET_ID 와 TOKEN 값을 채운다. (TOKEN은 아무 긴 임의 문자열)
 * 4) 배포 → 새 배포 → 유형: 웹 앱 → 실행: 나 → 액세스: 모든 사용자 → 배포.
 *    나오는 웹앱 URL(.../exec)을 복사.
 * 5) docs/index.html 의 APPS_SCRIPT_URL 에 그 URL을 붙여넣어 커밋.
 * 6) GitHub 저장소 → Settings → Secrets and variables → Actions 에서
 *    APPS_SCRIPT_URL = 웹앱 URL, ALERT_TOKEN = 위 TOKEN 값 을 등록.
 */

var SHEET_ID = "PASTE_YOUR_SHEET_ID_HERE";
var TOKEN = "PASTE_A_LONG_RANDOM_SECRET_HERE";  // GitHub의 ALERT_TOKEN과 동일해야 함

function sheet_() {
  var ss = SpreadsheetApp.openById(SHEET_ID);
  return ss.getSheetByName("subscribers") || ss.insertSheet("subscribers");
}

function doPost(e) {
  var p = (e && e.parameter) || {};
  var action = p.action || "subscribe";
  if (action === "alert") return handleAlert_(p);
  if (action === "unsubscribe") return unsubscribe_(p);
  return subscribe_(p);
}

function subscribe_(p) {
  var email = String(p.contact || "").trim();
  if (!email) return json_({ ok: false, error: "no contact" });
  var s = sheet_();
  // 중복 방지
  var data = s.getDataRange().getValues();
  for (var i = 1; i < data.length; i++) {
    if (String(data[i][2]).trim().toLowerCase() === email.toLowerCase()) {
      return json_({ ok: true, dup: true });
    }
  }
  s.appendRow([new Date(), "email", email]);
  return json_({ ok: true });
}

function unsubscribe_(p) {
  var email = String(p.contact || "").trim().toLowerCase();
  var s = sheet_(), data = s.getDataRange().getValues();
  for (var i = data.length - 1; i >= 1; i--) {
    if (String(data[i][2]).trim().toLowerCase() === email) s.deleteRow(i + 1);
  }
  return json_({ ok: true });
}

function handleAlert_(p) {
  if (String(p.token) !== TOKEN) return json_({ ok: false, error: "forbidden" });
  var subject = p.subject || "[카타르항공 운항 알림]";
  var body = p.body || "";
  var data = sheet_().getDataRange().getValues();
  var sent = 0;
  for (var i = 1; i < data.length; i++) {
    var email = String(data[i][2]).trim();
    if (!email) continue;
    try {
      MailApp.sendEmail(email, subject, body);
      sent++;
    } catch (err) { /* 개별 실패는 무시하고 계속 */ }
  }
  return json_({ ok: true, sent: sent });
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
