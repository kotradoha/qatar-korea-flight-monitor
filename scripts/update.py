#!/usr/bin/env python3
"""
카타르항공 도하<->인천 운항 모니터 - 데이터 수집 스크립트
GitHub Actions에서 매시간 실행되어 docs/data.json 을 갱신한다.

데이터 출처:
  - FlightStats(Cirium) 비공식 JSON 엔드포인트 (v2 웹페이지가 사용하는 것과 동일)
  - 카타르항공 공식 travel-alerts 페이지 (한국 노선/영공 관련 공지 감지)
  - SafeAirspace (카타르 영공 권고)
  - adsb.lol (실시간 항공기 위치, 커뮤니티 ADS-B)

status kind 값 (프론트에서 한/영 라벨로 변환):
  sched / inflight / landed / cancelled / diverted / delayed
  plan (정기 스케줄상 예정) / no_service (스케줄상 운항 없음) / checking
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "docs" / "data.json"

TZ_DOHA = ZoneInfo("Asia/Qatar")
TZ_SEOUL = ZoneInfo("Asia/Seoul")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

FLIGHTS = {
    "QR858": {
        "route": "도하 (DOH) → 인천 (ICN)",
        "route_en": "Doha (DOH) → Incheon (ICN)",
        "origin_tz": "doha",
        "sched_dep": "02:20",
        "sched_arr": "17:05",
        "labels": {"dep": "출발 (도하)", "arr": "도착 (인천)"},
        "labels_en": {"dep": "Departure (Doha)", "arr": "Arrival (Incheon)"},
        "daily": True,
        "note": "매일 운항 · A350-1000",
        "note_en": "Daily · A350-1000",
    },
    "QR859": {
        "route": "인천 (ICN) → 도하 (DOH)",
        "route_en": "Incheon (ICN) → Doha (DOH)",
        "origin_tz": "seoul",
        "sched_dep": "01:20",
        "sched_arr": "05:20",
        "labels": {"dep": "출발 (인천)", "arr": "도착 (도하)"},
        "labels_en": {"dep": "Departure (Incheon)", "arr": "Arrival (Doha)"},
        "daily": True,
        "note": "매일 운항 · A350-1000",
        "note_en": "Daily · A350-1000",
    },
    "QR862": {
        "route": "도하 (DOH) → 인천 (ICN)",
        "route_en": "Doha (DOH) → Incheon (ICN)",
        "origin_tz": "doha",
        "sched_dep": "19:45",
        "sched_arr": "익일 10:30",
        "labels": {"dep": "출발 (도하)", "arr": "도착 (인천)"},
        "labels_en": {"dep": "Departure (Doha)", "arr": "Arrival (Incheon)"},
        "daily": False,
        "note": "비정기 운항 (최근 목요일 위주) · 스케줄에 없는 날은 결항 아님",
        "note_en": "Not daily (recently Thursdays) · absence from schedule is not a cancellation",
    },
}

DOW_KR = ["월", "화", "수", "목", "금", "토", "일"]
DOW_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

DELAY_ALERT_MIN = 20  # 분

# 핵심 3편(858/859/862) 외에 도하<->인천을 운항할 수 있는 QR 편명 후보.
# 매시간 스캔하여 실제 편성이 확인되면 임시·추가편으로 대시보드에 자동 추가한다.
# 임시 증편이 다른 번호로 생기면 이 목록에 편명만 추가하면 된다.
EXTRA_CANDIDATES = ["860", "864", "866", "868", "870", "872", "876", "888"]
ROUTE_APS = {"DOH", "ICN"}


def tz_of(key):
    return TZ_DOHA if key == "doha" else TZ_SEOUL


def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_flight(number, d):
    """FlightStats JSON. number: '858', d: date (출발지 현지)."""
    url = (f"https://www.flightstats.com/v2/api-next/flight-tracker/"
           f"QR/{number}/{d.year}/{d.month}/{d.day}")
    try:
        raw = json.loads(http_get(url))
    except Exception as e:
        print(f"[warn] QR{number} {d}: fetch failed: {e}", file=sys.stderr)
        return None
    data = raw.get("data") or {}
    if not data or not data.get("status"):
        return None
    sched = data.get("schedule") or {}
    status = data.get("status") or {}
    note = data.get("flightNote") or {}
    delay = status.get("delay") or {}

    def mins(side):
        try:
            return int(((delay.get(side) or {}).get("minutes")) or 0)
        except (TypeError, ValueError):
            return 0

    code = (status.get("statusCode") or "U").upper()
    if note.get("canceled"):
        code = "C"
    dep_ap = ((data.get("departureAirport") or {}).get("fs") or "").upper()
    arr_ap = ((data.get("arrivalAirport") or {}).get("fs") or "").upper()
    return {
        "code": code,
        "dep_ap": dep_ap,
        "arr_ap": arr_ap,
        "dep_sched_utc": sched.get("scheduledDepartureUTC"),
        "arr_sched_utc": sched.get("scheduledArrivalUTC"),
        "dep_est_utc": sched.get("estimatedActualDepartureUTC"),
        "arr_est_utc": sched.get("estimatedActualArrivalUTC"),
        "delay_dep": mins("departure"),
        "delay_arr": mins("arrival"),
    }


def to_local(utc_str, tz):
    if not utc_str:
        return None
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return dt.astimezone(tz).strftime("%H:%M")
    except ValueError:
        return None


def fetch_position(callsign):
    """adsb.lol 커뮤니티 ADS-B 데이터로 실시간 위치 (비행 중일 때만 결과 있음)."""
    try:
        raw = json.loads(http_get(f"https://api.adsb.lol/v2/callsign/{callsign}"))
        ac = (raw.get("ac") or [])
        if not ac:
            return None
        a = ac[0]
        return {
            "lat": a.get("lat"),
            "lon": a.get("lon"),
            "alt_ft": a.get("alt_baro"),
            "gs_kt": a.get("gs"),
            "callsign": callsign,
            "seen_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "adsb.lol",
        }
    except Exception as e:
        print(f"[warn] position {callsign}: {e}", file=sys.stderr)
        return None


def fetch_qa_alerts():
    """카타르항공 공식 travel-alerts 페이지에서 한국 노선/영공 관련 언급 감지."""
    try:
        html = http_get("https://www.qatarairways.com/en/travel-alerts.html")
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        keywords = ["seoul", "incheon", "korea", "airspace", "suspend",
                    "cancell", "iran", "doha operations"]
        hits, seen = [], set()
        low = text.lower()
        for kw in keywords:
            for m in re.finditer(re.escape(kw), low):
                s = max(0, m.start() - 120)
                snippet = text[s:m.end() + 160].strip()
                key = snippet[:80]
                if key not in seen:
                    seen.add(key)
                    hits.append({"keyword": kw, "snippet": snippet})
        return {
            "ok": True,
            "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "https://www.qatarairways.com/en/travel-alerts.html",
            "korea_route_mentions": hits[:5],
        }
    except Exception as e:
        print(f"[warn] QA alerts fetch failed: {e}", file=sys.stderr)
        return {"ok": False}


def parse_advisories(text):
    """SafeAirspace 본문에서 권고 코드(CZIB/NOTAM 등)와 유효기간(valid until/through)을 추출."""
    advisories = []
    # 권고 코드: 'EASA CZIB 2026-07', 'France NOTAM LFFF F1553/26', 'NOTAM A1234/26' 등
    code_re = re.compile(
        r"((?:EASA\s+CZIB\s*[0-9\-]+)|(?:[A-Za-z ]{0,20}?NOTAM\s+[A-Z]{0,4}\s?[A-Z]?[0-9]{2,4}/[0-9]{2}))",
        re.IGNORECASE)
    date_re = re.compile(
        r"valid\s+(?:through|until|to)\s+([A-Za-z]+\s+\d{1,2},?\s*\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        re.IGNORECASE)
    seen = set()
    for m in code_re.finditer(text):
        code = re.sub(r"\s+", " ", m.group(1)).strip(" .,")
        if code.lower() in seen or len(code) < 5:
            continue
        seen.add(code.lower())
        # 코드 근처(뒤쪽 200자)에서 유효기간 탐색
        tail = text[m.end():m.end() + 220]
        dm = date_re.search(tail)
        advisories.append({"code": code, "valid_until": dm.group(1).strip() if dm else None})
        if len(advisories) >= 6:
            break
    return advisories


def fetch_airspace(prev):
    """SafeAirspace 카타르 페이지에서 위험 등급·폐쇄 여부·권고 유효기간 추출. 실패 시 이전 값 유지."""
    try:
        html = http_get("https://safeairspace.net/qatar/")
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        low = text.lower()
        m = re.search(r"(?:Risk\s*)?Level[:\s]*([A-Za-z]+)", text)
        # 영공 '폐쇄'로 판단하는 보수적 키워드 (단순 권고/주의는 폐쇄 아님)
        closed = bool(re.search(
            r"airspace\s+clos|fully\s+clos|closed\s+to\s+all|"
            r"complete\s+clos|suspend(ed)?\s+all\s+flight|no\s+overflight",
            low))
        return {
            "risk_level": m.group(1).strip() if m else None,
            "closed": closed,
            "status": "closed" if closed else "open",
            "advisories": parse_advisories(text),
            "source": "https://safeairspace.net/qatar/",
            "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ok": True,
        }
    except Exception as e:
        print(f"[warn] airspace fetch failed: {e}", file=sys.stderr)
        old = (prev or {}).get("airspace") or {}
        old["ok"] = False
        return old


def discover_extra_flights(now_utc, alerts):
    """핵심편 외 도하<->인천 QR 임시·추가편을 스캔해 flights_out 항목 dict를 반환."""
    core = {f[2:] for f in FLIGHTS}
    doha_today = now_utc.astimezone(TZ_DOHA).date()
    found = {}
    for num in EXTRA_CANDIDATES:
        if num in core:
            continue
        try:
            days, direction = [], None
            badge = {"state": "good", "kind": "normal"}
            for offset in range(-1, 4):
                d = doha_today + timedelta(days=offset)
                fs = fetch_flight(num, d)
                if not fs:
                    continue
                if fs["dep_ap"] not in ROUTE_APS or fs["arr_ap"] not in ROUTE_APS:
                    continue  # 도하<->인천 노선이 아니면 무시
                if fs["dep_ap"] == fs["arr_ap"]:
                    continue
                dep_tz = TZ_SEOUL if fs["dep_ap"] == "ICN" else TZ_DOHA
                arr_tz = TZ_SEOUL if fs["arr_ap"] == "ICN" else TZ_DOHA
                if direction is None:
                    direction = (fs["dep_ap"], fs["arr_ap"])
                code = fs["code"]
                dep_t = to_local(fs["dep_est_utc"], dep_tz) or to_local(fs["dep_sched_utc"], dep_tz)
                arr_t = to_local(fs["arr_est_utc"], arr_tz) or to_local(fs["arr_sched_utc"], arr_tz)
                worst = max(fs["delay_dep"], fs["delay_arr"])
                entry = {
                    "date": d.isoformat(),
                    "label": f"{d.month}/{d.day} ({DOW_KR[d.weekday()]})",
                    "label_en": f"{DOW_EN[d.weekday()]} {d.month}/{d.day}",
                    "dep": dep_t or "—", "arr": arr_t or "—",
                    "kind": "sched", "cls": "good", "delay": worst, "confirmed": True,
                }
                fno = "QR" + num
                if code == "C":
                    entry["kind"], entry["cls"] = "cancelled", "crit"
                    alerts.append({"flight": fno, "date": d.isoformat(), "type": "cancelled"})
                    if offset >= 0:
                        badge = {"state": "crit", "kind": "cancelled"}
                elif code in ("D", "R"):
                    entry["kind"], entry["cls"] = "diverted", "crit"
                    alerts.append({"flight": fno, "date": d.isoformat(), "type": "diverted"})
                    badge = {"state": "crit", "kind": "diverted"}
                elif worst >= DELAY_ALERT_MIN and code in ("S", "A"):
                    entry["kind"], entry["cls"] = "delayed", "warn"
                    alerts.append({"flight": fno, "date": d.isoformat(), "type": "delay", "minutes": worst})
                    if offset >= 0 and badge["state"] == "good":
                        badge = {"state": "warn", "kind": "delayed", "delay": worst}
                else:
                    entry["kind"] = {"S": "sched", "A": "inflight", "L": "landed"}.get(code, "sched")
                days.append(entry)

            if not days or direction is None:
                continue  # 운항 미확인 → 표시하지 않음
            dep_ap, arr_ap = direction
            if arr_ap == "ICN":
                route = "도하 (DOH) → 인천 (ICN)"; route_en = "Doha (DOH) → Incheon (ICN)"
                labels = {"dep": "출발 (도하)", "arr": "도착 (인천)"}
                labels_en = {"dep": "Departure (Doha)", "arr": "Arrival (Incheon)"}
            else:
                route = "인천 (ICN) → 도하 (DOH)"; route_en = "Incheon (ICN) → Doha (DOH)"
                labels = {"dep": "출발 (인천)", "arr": "도착 (도하)"}
                labels_en = {"dep": "Departure (Incheon)", "arr": "Arrival (Doha)"}
            fno = "QR" + num
            found[fno] = {
                "route": route, "route_en": route_en,
                "labels": labels, "labels_en": labels_en,
                "daily": False, "temp": True,
                "note": "임시·추가 편성 (자동 감지)",
                "note_en": "Temporary / extra service (auto-detected)",
                "badge": badge, "days": days,
                "position": fetch_position(f"QTR{num}"),
                "fr24": f"https://www.flightradar24.com/data/flights/qr{num}",
            }
        except Exception as e:
            print(f"[warn] extra scan QR{num}: {e}", file=sys.stderr)
            continue
    return found


def main():
    prev = None
    if DATA_PATH.exists():
        try:
            prev = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = None

    now_utc = datetime.now(timezone.utc)
    alerts = []
    flights_out = {}

    for fno, cfg in FLIGHTS.items():
        num = fno[2:]
        tz = tz_of(cfg["origin_tz"])
        arr_tz = TZ_SEOUL if "ICN)" in cfg["route"].split("→")[1] else TZ_DOHA
        today_local = now_utc.astimezone(tz).date()
        days = []
        badge = {"state": "good", "kind": "normal"}

        for offset in range(-1, 7):
            d = today_local + timedelta(days=offset)
            entry = {
                "date": d.isoformat(),
                "label": f"{d.month}/{d.day} ({DOW_KR[d.weekday()]})",
                "label_en": f"{DOW_EN[d.weekday()]} {d.month}/{d.day}",
                "dep": cfg["sched_dep"],
                "arr": cfg["sched_arr"],
                "kind": "plan" if cfg["daily"] else "checking",
                "cls": "plan",
                "delay": 0,
                "confirmed": False,
            }
            if -1 <= offset <= 3:  # FlightStats 개별 편 조회 가능 범위
                fs = fetch_flight(num, d)
                if fs:
                    code = fs["code"]
                    dep_t = to_local(fs["dep_est_utc"], tz) or to_local(fs["dep_sched_utc"], tz)
                    arr_t = to_local(fs["arr_est_utc"], arr_tz) or to_local(fs["arr_sched_utc"], arr_tz)
                    entry.update({"dep": dep_t or cfg["sched_dep"],
                                  "arr": arr_t or cfg["sched_arr"],
                                  "confirmed": True})
                    worst = max(fs["delay_dep"], fs["delay_arr"])
                    entry["delay"] = worst
                    if code == "C":
                        entry["kind"], entry["cls"] = "cancelled", "crit"
                        alerts.append({"flight": fno, "date": d.isoformat(),
                                       "type": "cancelled"})
                        if offset >= 0:
                            badge = {"state": "crit", "kind": "cancelled"}
                    elif code in ("D", "R"):
                        entry["kind"], entry["cls"] = "diverted", "crit"
                        alerts.append({"flight": fno, "date": d.isoformat(),
                                       "type": "diverted"})
                        badge = {"state": "crit", "kind": "diverted"}
                    elif worst >= DELAY_ALERT_MIN and code in ("S", "A"):
                        entry["kind"], entry["cls"] = "delayed", "warn"
                        alerts.append({"flight": fno, "date": d.isoformat(),
                                       "type": "delay", "minutes": worst})
                        if offset >= 0 and badge["state"] == "good":
                            badge = {"state": "warn", "kind": "delayed",
                                     "delay": worst}
                    else:
                        entry["kind"] = {"S": "sched", "A": "inflight",
                                         "L": "landed"}.get(code, "sched")
                        entry["cls"] = "good"
                elif not cfg["daily"]:
                    entry["kind"], entry["cls"] = "no_service", "plan"
                    entry["dep"] = entry["arr"] = "—"
            if offset == -1 and not entry["confirmed"]:
                continue
            days.append(entry)

        position = fetch_position(f"QTR{num}")
        if position and badge == {"state": "good", "kind": "normal"}:
            badge = {"state": "good", "kind": "inflight"}

        out_cfg = {k: v for k, v in cfg.items() if k != "origin_tz"}
        flights_out[fno] = {**out_cfg, "badge": badge, "days": days,
                            "position": position,
                            "fr24": f"https://www.flightradar24.com/data/flights/qr{num}"}

    # 임시·추가 항공편 자동 감지 (실패해도 핵심 대시보드에는 영향 없음)
    core_order = list(FLIGHTS.keys())
    try:
        extra = discover_extra_flights(now_utc, alerts)
    except Exception as e:
        print(f"[warn] discover_extra_flights failed: {e}", file=sys.stderr)
        extra = {}
    for fno, data_f in extra.items():
        flights_out[fno] = data_f
    order = core_order + sorted(extra.keys())

    airspace = fetch_airspace(prev)
    qa_alerts = fetch_qa_alerts()
    if not qa_alerts.get("ok") and prev:
        qa_alerts = (prev.get("qa_alerts") or {"ok": False})

    out = {
        "generated_at_utc": now_utc.isoformat(timespec="seconds"),
        "generated_at_doha": now_utc.astimezone(TZ_DOHA).strftime("%Y-%m-%d %H:%M"),
        "generated_at_seoul": now_utc.astimezone(TZ_SEOUL).strftime("%Y-%m-%d %H:%M"),
        "airspace": airspace,
        "qa_alerts": qa_alerts,
        "alerts": alerts,
        "order": order,
        "flights": flights_out,
    }
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    print(f"wrote {DATA_PATH} — alerts: {len(alerts)}")


if __name__ == "__main__":
    main()
