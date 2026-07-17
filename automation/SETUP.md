# 이메일 자동 발송 설정 가이드

영공 폐쇄·지연·결항이 감지되면 구독자 전원에게 **이메일이 자동 발송**되도록 하는 설정입니다.
문자(SMS)는 무료로 안정적인 방법이 없어 제외했고, 이메일만 사용합니다. 전부 무료입니다.

## 구조

```
구독자 (웹페이지)                     GitHub Actions (매시간)
   │ 구독/취소                            │ 운항 상태 확인
   ▼                                      ▼ 새 알림 발생 시
Google Apps Script  ◀──── 알림 전송 ──── notify.py
   │ (구글 시트에 구독자 저장)
   ▼ 자동 이메일 발송
구독자 받은편지함
```

## 1단계 — 구글 시트 + 앱스스크립트

1. `qatarandkorea@gmail.com` 으로 로그인 후 https://sheets.new 로 새 시트를 만듭니다.
2. 왼쪽 아래 시트 탭 이름을 `subscribers` 로 바꾸고, 1행에 `time`, `type`, `contact` 를 입력합니다.
3. 주소창의 `docs.google.com/spreadsheets/d/`**`이 부분`**`/edit` 에서 시트 ID를 복사합니다.
4. https://script.google.com → **새 프로젝트** → `automation/apps_script.gs` 의 코드 전체를 붙여넣습니다.
5. 코드 상단 `SHEET_ID` 에 3번의 ID를, `TOKEN` 에 아무 긴 임의 문자열(예: 32자 랜덤)을 넣습니다.
6. 오른쪽 위 **배포 → 새 배포 → 유형: 웹 앱** → 실행 대상: **나**, 액세스 권한: **모든 사용자** → **배포**.
   - 처음 배포 시 권한 승인 창이 뜨면 허용합니다.
7. 나온 **웹 앱 URL**(`.../exec` 로 끝남)을 복사합니다.

## 2단계 — 웹페이지에 연결

`docs/index.html` 상단의 다음 줄을 찾아 URL을 붙여넣고 커밋합니다.

```js
var APPS_SCRIPT_URL = "";   // ← 여기에 1단계 7번의 웹앱 URL
```

이제 웹페이지 구독/취소가 구글 시트에 저장됩니다. (비워두면 이메일 수집만 되고 자동발송은 꺼짐)

## 3단계 — GitHub 비밀값 등록

저장소 → **Settings → Secrets and variables → Actions → New repository secret** 에서 두 개를 등록합니다.

| 이름 | 값 |
|---|---|
| `APPS_SCRIPT_URL` | 1단계 7번의 웹앱 URL |
| `ALERT_TOKEN` | 1단계 5번에 넣은 TOKEN 과 동일한 문자열 |

## 완료

이후 매시간 자동 점검에서 새 알림이 감지되면 `notify.py` 가 앱스스크립트로 알림을 보내고,
앱스스크립트가 구독자 전원에게 이메일을 발송합니다. 같은 알림은 한 번만 발송됩니다
(`docs/notify_state.json` 에 발송 이력 기록).

## 참고

- 발송 이메일은 `qatarandkorea@gmail.com` 에서 나갑니다(앱스스크립트 소유 계정).
- 지메일 자동발송 한도: 일반 계정 약 100건/일, Workspace 계정 약 1,500건/일.
  구독자가 많아지면 전용 이메일 발송 서비스(SendGrid 등, 무료 티어 있음)로 확장할 수 있습니다.
- 문자(SMS) 발송이 꼭 필요하면 Twilio 같은 유료 서비스 연동이 필요합니다(요청 시 추가 구성 가능).
