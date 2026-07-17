#!/usr/bin/env python3
"""
알림 자동 발송 트리거 (GitHub Actions에서 update.py 직후 실행).

동작:
  1. docs/data.json 의 alerts + 영공 폐쇄 상태를 읽는다.
  2. docs/notify_state.json 에 기록된 '이미 발송한 알림'과 비교해 새 알림만 추린다.
  3. 새 알림이 있으면 Google Apps Script 웹앱(APPS_SCRIPT_URL)에 POST 한다.
     → 앱스스크립트가 구독자 시트를 읽어 이메일/문자로 발송한다.
  4. 발송한 알림 키를 상태 파일에 저장한다.

환경변수(리포지토리 Secrets):
  APPS_SCRIPT_URL : 앱스스크립트 웹앱 /exec URL
  ALERT_TOKEN     : 앱스스크립트에 설정한 것과 동일한 비밀 토큰
둘 중 하나라도 없으면 조용히 종료(발송 안 함).
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "docs" / "data.json"
STATE_PATH = ROOT / "docs" / "notify_state.json"

DASH = "kotradoha.github.io/qatar-korea-flight-monitor"


def load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def event_key(a):
    if a.get("type") == "airspace_closed":
        return "airspace_closed"
    return f"{a.get('flight')}|{a.get('date')}|{a.get('type')}"


def kr_line(a):
    fl = a.get("flight", "")
    dt = (a.get("date", "") or "").replace("-", "/")[5:]
    if a.get("type") == "cancelled":
        return f"✕ {fl} ({dt}) 결항"
    if a.get("type") == "diverted":
        return f"⚠ {fl} ({dt}) 회항"
    if a.get("type") == "delay":
        return f"⏱ {fl} ({dt}) 약 {a.get('minutes','?')}분 지연"
    if a.get("type") == "airspace_closed":
        return "⚠️ 카타르(도하 하마드) 영공 폐쇄 감지 — 인천 노선 차질 가능"
    return f"{fl} ({dt}) 상태 변경"


def main():
    url = os.environ.get("APPS_SCRIPT_URL", "").strip()
    token = os.environ.get("ALERT_TOKEN", "").strip()

    data = load(DATA_PATH, {})
    alerts = list(data.get("alerts") or [])
    if (data.get("airspace") or {}).get("closed"):
        alerts = [{"type": "airspace_closed"}] + alerts

    state = load(STATE_PATH, {"sent": []})
    sent = set(state.get("sent") or [])

    new = [a for a in alerts if event_key(a) not in sent]
    if not new:
        print("notify: 새 알림 없음")
        return

    lines = [kr_line(a) for a in new]
    subject = "[카타르항공 운항 알림] " + (lines[0] if len(lines) == 1 else f"{len(lines)}건 발생")
    body = ("카타르항공 도하↔인천 노선 알림입니다.\n\n" +
            "\n".join("· " + ln for ln in lines) +
            f"\n\n최신 상황: https://{DASH}/\n예약·변경 최종 확인은 카타르항공 공식 채널(https://fs.qatarairways.com/)을 이용하세요.")

    if not url or not token:
        print("notify: APPS_SCRIPT_URL/ALERT_TOKEN 미설정 → 발송 생략 (아래 새 알림만 기록)", file=sys.stderr)
        print("\n".join(lines))
    else:
        payload = urllib.parse.urlencode({
            "action": "alert", "token": token,
            "subject": subject, "body": body,
        }).encode()
        try:
            req = urllib.request.Request(url, data=payload,
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=30) as r:
                print("notify: 발송 요청 완료", r.status)
        except Exception as e:
            print(f"notify: 발송 실패 (상태는 기록하지 않음): {e}", file=sys.stderr)
            return  # 실패 시 상태 미기록 → 다음 실행에서 재시도

    for a in new:
        sent.add(event_key(a))
    # 상태 파일이 무한정 커지지 않도록 최근 500개만 유지
    state["sent"] = list(sent)[-500:]
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"notify: 새 알림 {len(new)}건 처리")


if __name__ == "__main__":
    main()
