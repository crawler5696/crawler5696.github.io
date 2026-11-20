#!/usr/bin/env python3
"""공개 일봉 125봉 차트 자료 — 뉴스 · 상한가 · 테마달력 · 레이더에서 종목을 눌렀을 때 여는 차트.

결과: data/day125.json  (평문 — 공개해도 되는 시세만)
      종목코드 → 최근 125거래일 일봉(시·고·저·종·거래량)

이 파일에는 개인 판단(기준선·1~10단계·유형·앞쪽/뒷쪽·핫바·점수)이 **하나도** 없다.
비밀 핫바 잠금(5696)과 무관하게, 공개 메뉴에서 누구나 볼 수 있는 시세만 담는다.

대상 종목 = 공개 화면에 이름이 뜨는 종목 전부
  · data/calendar.json (테마달력 12개월)의 상한가 종목
  · data/news.json upper_limits (오늘 상한가)
  · data/radar.json (레이더)
  · news.json 기사 leaders(관련 종목 이름) → 이름으로 코드를 찾아 포함

날짜는 한 벌(dates)만 담고 종목마다 그 안의 자리(o0 / x)만 적어 파일을 가볍게 유지한다.
받지 못한 종목은 이미 있는 day125.json 의 봉을 그대로 둔다(차트가 비지 않게).

사용
  python3 scripts/build_day125.py                 # 받아서 갱신
  python3 scripts/build_day125.py --days 125 --workers 16
  python3 scripts/build_day125.py --min-age-min 180   # 180분 안에 만든 자료면 건너뛴다
  python3 scripts/build_day125.py --max-codes 20      # 시험용
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)                       # projects/stock-news-radar
DATA = os.path.join(SITE, "data")
OUT = os.path.join(DATA, "day125.json")
KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"}


def jload(name):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def wanted_codes() -> tuple[list[str], dict[str, str]]:
    """공개 화면에 이름이 뜨는 종목 (코드, 이름표)."""
    codes: list[str] = []
    names: dict[str, str] = {}

    def add(code, name=""):
        c = str(code or "").strip()
        if not c or not c.isdigit() or len(c) != 6:
            return
        if c not in names:
            codes.append(c)
        if name:
            names.setdefault(c, str(name).strip())

    cal = jload("calendar.json")
    for m in cal.get("months") or []:
        for t in m.get("themes") or []:
            for s in t.get("stocks") or []:
                add(s.get("code"), s.get("name"))

    news = jload("news.json")
    for it in ((news.get("upper_limits") or {}).get("items") or []):
        add(it.get("code"), it.get("name"))

    radar = jload("radar.json")
    for t in radar.get("tiers") or []:
        for s in t.get("stocks") or []:
            add(s.get("code"), s.get("name"))

    # 기사 관련 종목(leaders)은 이름만 온다 — 이미 아는 이름표에서 코드를 찾아 넣는다
    by_name = {v: k for k, v in names.items() if v}
    for key in ("flash", "issues", "articles"):
        for a in news.get(key) or []:
            for nm in a.get("leaders") or []:
                c = by_name.get(str(nm).strip())
                if c:
                    add(c, str(nm).strip())
    return codes, names


def fetch_bars(code: str, count: int = 130):
    """네이버 일봉 — 마지막 봉이 오늘(장중이면 진행 중인 봉)이다. 봉 = [날짜, 시, 고, 저, 종, 거래량]"""
    url = ("https://fchart.stock.naver.com/sise.nhn?symbol=%s&timeframe=day&count=%d&requestType=0"
           % (code, count))
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("euc-kr", errors="replace")
            root = ET.fromstring(raw)
            rows = []
            for item in root.findall(".//item"):
                p = item.attrib.get("data", "").split("|")
                if len(p) < 6 or "null" in p[1:5]:
                    continue
                d = p[0]
                try:
                    rows.append(["%s-%s-%s" % (d[:4], d[4:6], d[6:8]),
                                 float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5])])
                except ValueError:
                    continue
            rows = [r for r in rows if min(r[1:5]) > 0]
            if rows:
                return rows
        except Exception:
            time.sleep(0.3 * (attempt + 1))
    return []


def encode(stock_rows: dict[str, list[list]], names: dict[str, str], days: int) -> dict:
    """종목별 최근 days봉 → {dates:[YYMMDD...], stocks:{code:{n,b,o0|x}}}"""
    cut: dict[str, list[list]] = {}
    for c, rows in stock_rows.items():
        rows = sorted(rows, key=lambda r: r[0])[-days:]
        if len(rows) >= 20:
            cut[c] = rows
    axis = sorted({r[0] for rows in cut.values() for r in rows})
    at = {d: i for i, d in enumerate(axis)}
    stocks = {}
    for c, rows in cut.items():
        bars = [[int(round(r[1])), int(round(r[2])), int(round(r[3])),
                 int(round(r[4])), int(round(r[5]))] for r in rows]
        idx = [at[r[0]] for r in rows]
        rec = {"n": names.get(c, c), "b": bars}
        if idx == list(range(idx[0], idx[0] + len(idx))):
            rec["o0"] = idx[0]                      # 날짜가 끊기지 않는다 — 시작 자리만
        else:
            rec["x"] = idx
        stocks[c] = rec
    return {"dates": [int(d[2:4] + d[5:7] + d[8:10]) for d in axis], "stocks": stocks, "days": days}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=125)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--count", type=int, default=0, help="받아올 봉 수(기본 days+5)")
    ap.add_argument("--min-age-min", type=int, default=0)
    ap.add_argument("--max-codes", type=int, default=0)
    args = ap.parse_args()
    count = args.count or (args.days + 5)

    old = {}
    try:
        with open(OUT, encoding="utf-8") as f:
            old = json.load(f)
    except Exception:
        old = {}
    if args.min_age_min and old.get("generated_at"):
        try:
            age = (datetime.now(KST) - datetime.fromisoformat(old["generated_at"])).total_seconds() / 60
            if age < args.min_age_min:
                print("일봉 125봉 자료가 %d분 전 자료라 건너뜁니다 (%s)" % (int(age), old["generated_at"]))
                return
        except Exception:
            pass

    codes, names = wanted_codes()
    if args.max_codes:
        codes = codes[:args.max_codes]
    if not codes:
        print("공개 화면에 종목이 없습니다 — data/*.json 을 확인하세요", file=sys.stderr)
        return

    t0 = time.time()
    got: dict[str, list[list]] = {}
    miss: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for c, rows in zip(codes, ex.map(lambda x: fetch_bars(x, count), codes)):
            if rows:
                got[c] = rows
            else:
                miss.append(c)

    # 이미 있던 봉은 날짜로 합친다 — 오늘 못 받은 종목도 어제까지의 봉은 남는다
    old_dates = old.get("dates") or []
    old_stocks = old.get("stocks") or {}
    merged: dict[str, list[list]] = {}
    for c in codes:
        rows = list(got.get(c) or [])
        o = old_stocks.get(c)
        if o and o.get("b"):
            seen = {r[0] for r in rows}
            idx = o.get("x") or (list(range(o.get("o0", 0), o.get("o0", 0) + len(o["b"]))))
            for k, b in enumerate(o["b"]):
                if k >= len(idx) or idx[k] >= len(old_dates):
                    continue
                n = old_dates[idx[k]]
                day = "20%02d-%02d-%02d" % (n // 10000, (n // 100) % 100, n % 100)
                if day in seen:
                    continue
                rows.append([day, b[0], b[1], b[2], b[3], b[4], b[5] if len(b) > 5 else 0])
        if rows:
            merged[c] = rows

    enc = encode(merged, names, args.days)
    if not enc["stocks"]:
        print("받은 종목이 없습니다 — 네트워크를 확인하세요", file=sys.stderr)
        sys.exit(1)

    as_of = ""
    for c, rows in merged.items():
        if c in enc["stocks"]:
            as_of = max(as_of, max(r[0] for r in rows))
    doc = {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "as_of": as_of,
        "days": args.days,
        "dates": enc["dates"],
        "stocks": enc["stocks"],
        "names": {v: c for c, v in names.items() if c in enc["stocks"] and v},
    }
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT)
    bars_n = sum(len(v["b"]) for v in doc["stocks"].values())
    print("일봉 125봉 차트 %d종목 · 봉 %d · %s · %.0f초 · %.0fKB%s"
          % (len(doc["stocks"]), bars_n, as_of, time.time() - t0,
             os.path.getsize(OUT) / 1024,
             (" · 못 받은 종목 %d(이전 봉 유지)" % len(miss)) if miss else ""), flush=True)


if __name__ == "__main__":
    main()
