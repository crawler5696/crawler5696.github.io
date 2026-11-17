#!/usr/bin/env python3
"""국내 증시 뉴스 수집기 — 네이버 뉴스 경제 섹션(증권/산업/금융/글로벌경제/경제일반)에서
기사를 모아 테마 태그를 붙이고, 1~2줄 요약과 함께 data/news.json 으로 저장한다.

외부 API 키 없이 표준 라이브러리만 사용한다 (GitHub Actions 러너에서 바로 실행 가능).
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

# 섹션: (섹션 id, 이름, 가중치)
SECTIONS = [
    (258, "증권", 1.00),
    (261, "산업/재계", 0.90),
    (259, "금융", 0.85),
    (262, "글로벌 경제", 0.70),
    (263, "경제 일반", 0.75),
]

MAX_ARTICLES = 60          # 대시보드에 남길 최대 기사 수
ARTICLE_LIMIT = 100        # 원문 조회까지 할 후보 기사 수
ARTICLE_FETCH_WORKERS = 12  # 본문/시각 조회 동시 요청 수

# --------------------------------------------------------------------------- 테마 사전
# (id, 화면 라벨, 색상, [(키워드, 가중치), ...])
THEMES = [
    ("semiconductor", "반도체·AI", "#5b8cff", [
        ("반도체", 3), ("HBM", 3), ("D램", 3), ("DRAM", 3), ("낸드", 3), ("파운드리", 3),
        ("웨이퍼", 3), ("소부장", 3), ("반도체 장비", 3), ("인공지능", 3), ("AI", 1),
        ("엔비디아", 3), ("GPU", 3), ("데이터센터", 2), ("온디바이스", 3), ("CCL", 3),
        ("기판", 2), ("삼성전자", 2), ("SK하이닉스", 3), ("한미반도체", 3), ("DB하이텍", 3),
        ("리노공업", 3), ("이오테크닉스", 3), ("HPSP", 3), ("주성엔지니어링", 3),
        ("챗GPT", 2), ("LLM", 3), ("클라우드", 1), ("메모리", 2), ("시스템반도체", 3),
    ]),
    ("robot", "로봇·자율주행", "#38d6a8", [
        ("로봇", 3), ("휴머노이드", 3), ("협동로봇", 3), ("자율주행", 3), ("모빌리티", 2),
        ("드론", 3), ("UAM", 3), ("피지컬 AI", 3), ("피지컬AI", 3), ("레인보우로보틱스", 3),
        ("웨어러블", 2), ("스마트팩토리", 2), ("자동화", 2),
    ]),
    ("defense", "방산·우주", "#f0a35e", [
        ("방산", 3), ("국방", 2), ("K방산", 3), ("미사일", 3), ("무기", 2), ("잠수함", 3),
        ("전투기", 3), ("우주", 2), ("위성", 3), ("발사체", 3), ("항공우주", 3),
        ("한화에어로스페이스", 3), ("LIG넥스원", 3), ("한국항공우주", 3), ("누리호", 3),
        ("스페이스X", 3), ("스타링크", 3), ("함정", 2), ("K9", 3), ("천궁", 3),
    ]),
    ("bio", "바이오·헬스케어", "#e564b8", [
        ("바이오", 3), ("제약", 2), ("신약", 3), ("임상", 3), ("FDA", 3), ("품목허가", 3),
        ("백신", 3), ("의료", 2), ("헬스케어", 2), ("비만치료", 3), ("CDMO", 3),
        ("위탁생산", 3), ("항암", 3), ("줄기세포", 3), ("유전자", 2), ("알테오젠", 3),
        ("셀트리온", 3), ("삼성바이오로직스", 3), ("기술수출", 2), ("신약 허가", 3),
    ]),
    ("battery", "2차전지·에너지", "#8bd450", [
        ("2차전지", 3), ("이차전지", 3), ("배터리", 3), ("리튬", 3), ("양극재", 3),
        ("음극재", 3), ("분리막", 3), ("전해질", 3), ("전기차", 3), ("충전", 1),
        ("태양광", 3), ("수소", 3), ("연료전지", 3), ("원전", 3), ("원자력", 3),
        ("전력", 2), ("송전", 3), ("변압기", 3), ("ESS", 3), ("에너지", 1), ("LNG", 3),
        ("유가", 2), ("정유", 3), ("SMR", 3), ("전력기기", 3), ("HD현대일렉트릭", 3),
        ("LS일렉트릭", 3), ("산일전기", 3),
    ]),
    ("policy", "정책·건설", "#c9a2ff", [
        ("정부", 1), ("정책", 2), ("국회", 2), ("법안", 3), ("규제", 2), ("건설", 3),
        ("재건축", 3), ("재개발", 3), ("부동산", 2), ("세제", 3), ("감세", 3),
        ("예산", 2), ("공공", 1), ("SOC", 3), ("인프라", 2), ("국토부", 2), ("금융위", 2),
        ("공정위", 2), ("대통령", 1), ("장관", 1), ("특별법", 3), ("지원책", 2), ("육성", 2),
    ]),
    ("geopolitics", "남북·지정학", "#ff8b8b", [
        ("남북", 3), ("북한", 3), ("개성", 3), ("경협", 3), ("금강산", 3), ("대북", 3),
        ("지정학", 3), ("관세", 3), ("무역", 2), ("트럼프", 2), ("미중", 3), ("중국", 1),
        ("일본", 1), ("수출규제", 3), ("제재", 2), ("러시아", 2), ("우크라이나", 2),
        ("중동", 3), ("이스라엘", 3), ("호르무즈", 3),
    ]),
    ("macro", "거시·환율·금리", "#7fd3e8", [
        ("환율", 3), ("원달러", 3), ("금리", 3), ("연준", 3), ("한은", 3),
        ("한국은행", 3), ("물가", 3), ("CPI", 3), ("국채", 3), ("달러", 2), ("코스피", 3),
        ("코스닥", 3), ("증시", 3), ("외국인", 2), ("공매도", 3), ("MSCI", 3), ("지수", 2),
        ("채권", 3), ("기준금리", 3), ("경기", 1), ("GDP", 3), ("무역수지", 3),
        ("나스닥", 2), ("다우", 2), ("FOMC", 3), ("국제유가", 3),
    ]),
    ("earnings", "실적·공시·수급", "#f5d06b", [
        ("실적", 3), ("영업이익", 3), ("매출", 2), ("상한가", 3), ("급등", 3), ("급락", 3),
        ("공시", 3), ("유상증자", 3), ("무상증자", 3), ("M&A", 3), ("인수", 2),
        ("합병", 3), ("IPO", 3), ("상장", 2), ("자사주", 3), ("배당", 3), ("목표주가", 3),
        ("수주", 3), ("공급계약", 3), ("특허", 2), ("지분", 2), ("최대주주", 3),
        ("특징주", 3), ("테마주", 3), ("투자경고", 3), ("거래정지", 3), ("감자", 3),
        ("어닝", 3), ("컨센서스", 3), ("주가", 2), ("주주", 2),
    ]),
]
THEME_LABEL = {tid: label for tid, label, _c, _k in THEMES}
THEME_COLOR = {tid: color for tid, _l, color, _k in THEMES}

# 증시와 무관한 기사(부동산 시세·생활정보 등)를 거르기 위한 최소 관련도
MIN_RELEVANCE = 6

STOP_RE = re.compile(r"[\u200b\xa0]+")


# --------------------------------------------------------------------------- 유틸
def fetch(url: str, encoding: str = "utf-8", timeout: int = 12, retries: int = 1) -> str:
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode(encoding, "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"fetch failed: {url} ({last})")


def strip_tags(s: str) -> str:
    s = re.sub(r"<script.*?</script>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_lib.unescape(s)
    s = STOP_RE.sub(" ", s)
    return " ".join(s.split()).strip()


def sentences(text: str):
    parts = re.split(r"(?<=[.!?。])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def make_summary(text: str, limit: int = 165) -> str:
    """앞 1~2문장을 문장 경계에서 잘라 깔끔한 요약을 만든다."""
    text = " ".join(text.split())
    if not text:
        return ""
    out = ""
    for s in sentences(text):
        if out and len(out) + len(s) + 1 > limit:
            break
        out = (out + " " + s).strip()
        if len(out) >= limit * 0.55:
            break
        if len(out) >= limit:
            break
    if len(out) > limit:
        cut = out[:limit].rstrip()
        if " " in cut:
            cut = cut[: cut.rfind(" ")]
        out = cut.rstrip(" ,·-—") + "…"
    return out


CAPTION_HINT = ("하고 있다", "찍고 있다", "제공", "왼쪽부터", "사진=", "자료사진", "연합뉴스", "뉴시스")


def looks_like_caption(s: str) -> bool:
    if len(s) < 45 and any(h in s for h in CAPTION_HINT):
        return True
    return any(h in s for h in ("왼쪽부터", "사진=", "자료사진"))


# --------------------------------------------------------------------------- 수집
ITEM_SPLIT = re.compile(r'<li class="sa_item')
URL_RE = re.compile(r'https://n\.news\.naver\.com/mnews/article/(\d+)/(\d+)')
TITLE_RE = re.compile(r'<strong class="sa_text_strong">(.*?)</strong>', re.S)
LEDE_RE = re.compile(r'<div class="sa_text_lede">(.*?)</div>', re.S)
PRESS_RE = re.compile(r'<div class="sa_text_press">(.*?)</div>', re.S)


def parse_section(section_id: int, name: str, weight: float):
    url = f"https://news.naver.com/breakingnews/section/101/{section_id}"
    try:
        page = fetch(url)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] section {name} failed: {e}", file=sys.stderr)
        return []
    out = []
    for chunk in ITEM_SPLIT.split(page)[1:]:
        m_url = URL_RE.search(chunk)
        m_title = TITLE_RE.search(chunk)
        if not (m_url and m_title):
            continue
        title = strip_tags(m_title.group(1))
        if not title or len(title) < 6:
            continue
        m_lede = LEDE_RE.search(chunk)
        m_press = PRESS_RE.search(chunk)
        aid = f"{m_url.group(1)}/{m_url.group(2)}"
        out.append({
            "id": aid,
            "title": title,
            "lede": strip_tags(m_lede.group(1)) if m_lede else "",
            "press": strip_tags(m_press.group(1)) if m_press else "",
            "url": f"https://n.news.naver.com/mnews/article/{aid}",
            "section": name,
            "weight": weight,
        })
    print(f"[info] section {name}: {len(out)} items", file=sys.stderr)
    return out


TIME_RE = re.compile(r'_ARTICLE_DATE_TIME[^>]*data-date-time="([^"]+)"')


def extract_body(page: str) -> str:
    """본문 영역(#dic_area)만 잘라낸다. 정규식 백트래킹을 피하려고 문자열 탐색으로 처리."""
    i = page.find('id="dic_area"')
    if i < 0:
        return ""
    start = page.find(">", i)
    if start < 0:
        return ""
    end = len(page)
    for marker in ('</article>', 'article_footer', 'media_end_categorize', 'id="comment'):
        j = page.find(marker, start)
        if j > start:
            end = min(end, j)
    return strip_tags(page[start + 1:end])


def enrich(article: dict) -> dict:
    """기사 원문 페이지에서 정확한 발행 시각과 본문 첫 문장을 가져온다."""
    if article.get("source") == "google":
        return article
    try:
        page = fetch(article["url"])
    except Exception:  # noqa: BLE001
        return article
    m_time = TIME_RE.search(page)
    if m_time:
        try:
            dt = datetime.strptime(m_time.group(1).strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
            article["time"] = dt.isoformat()
        except ValueError:
            pass
    if not article.get("lede") or len(article["lede"]) < 25:
        body = extract_body(page)
        if body:
            sents = [s for s in sentences(body) if not looks_like_caption(s)]
            article["body_lead"] = " ".join(sents[:2])
    return article


# --------------------------------------------------------------------------- 분류
def classify(article: dict):
    """키워드 적중 상위 3개만 합산해 테마 점수를 계산한다 (키워드가 많은 테마가 독점하는 것을 방지)."""
    title = article["title"]
    lede = article.get("lede", "") or ""
    text = title + " " + lede + " " + article.get("body_lead", "")
    best_tid, best_score, best_tags = "etc", 0, []
    for tid, _label, _color, kws in THEMES:
        hits = []
        for kw, w in kws:
            if kw not in text:
                continue
            pos = 3 if kw in title else (2 if kw in lede else 1)
            hits.append((w * pos, kw))
        if not hits:
            continue
        hits.sort(reverse=True)
        score = sum(h[0] for h in hits[:3])
        tags = [h[1] for h in hits[:4]]
        if score > best_score:
            best_tid, best_score, best_tags = tid, score, tags
    if best_tid == "etc":
        return "etc", [], 0
    relevance = best_score + int(article.get("weight", 0.7) * 2)
    return best_tid, best_tags[:4], relevance


# 테마 키워드가 약해도 이 말들이 있으면 증시 기사로 본다
MARKET_TERMS = ("주가", "증시", "코스피", "코스닥", "종목", "상한가", "급등", "급락", "투자자",
                "외국인", "기관", "공시", "실적", "영업이익", "수주", "공급계약", "목표주가",
                "특징주", "테마주", "상장", "IPO", "인수", "지분", "배당", "공모주", "주주")

# 증시 기사 판별용 강한 신호 (제목에 있으면 무조건 채택)
STRONG_MARKET = MARKET_TERMS + (
    "주식", "매수", "매도", "거래량", "시가총액", "공매도", "ETF", "선물", "옵션",
    "증권사", "리포트", "컨센서스", "어닝", "분기 실적", "3분기", "4분기", "영업익",
    "최대주주", "유상증자", "무상증자", "자사주", "액면분할", "감자", "관리종목",
    "투자의견", "목표가", "주가순자산", "PER", "PBR", "공모가", "수급", "반등", "약세",
    "강세", "폭락", "폭등", "상승 마감", "하락 마감",
)

# 상장사·핵심 기업 이름 (이 이름 + 사업 동작이 함께 나오면 증시 기사로 본다)
COMPANIES = (
    "삼성전자", "SK하이닉스", "삼전닉스", "현대차", "기아", "LG에너지솔루션", "삼성SDI",
    "삼성바이오로직스", "셀트리온", "한화에어로스페이스", "현대로템", "두산에너빌리티",
    "네이버", "카카오", "LG전자", "POSCO", "포스코", "롯데케미칼", "이마트", "CJ",
    "한화", "HD현대", "LS", "GS", "대한항공", "아모레", "하이브", "에코프로", "포스코퓨처엠",
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "메타", "아마존", "TSMC",
    "알테오젠", "유한양행", "한미약품", "HLB", "리가켐", "레인보우로보틱스", "로보티즈",
    "이오테크닉스", "한미반도체", "HPSP", "주성엔지니어링", "DB하이텍", "리노공업",
    "HD현대일렉트릭", "LS일렉트릭", "산일전기", "효성중공업", "한전기술", "두산에너빌",
    "LIG넥스원", "한국항공우주", "케이조선", "HD한국조선해양", "삼성중공업", "한화오션",
)

BUSINESS_ACTS = ("투자", "수주", "계약", "공급", "실적", "매출", "영업이익", "개발", "출시",
                 "증설", "인수", "합병", "상장", "임상", "특허", "감산", "증산", "가격 인상",
                 "MOU", "협약", "납품", "진출", "점유율", "생산", "공장")

# 기업 이름이 나와도 증시와 무관한 행사·사훈성 기사
NOT_MARKET = ("수상", "나눔", "봉사", "기부", "축제", "점등", "전시", "공연", "시상",
              "행사", "개막", "박람회", "체험", "공모전", "졸업", "입학")


def is_market_relevant(a: dict) -> bool:
    """증시와 무관한 생활·지역 뉴스를 걸러낸다."""
    title = a["title"]
    lede = a.get("lede", "") or ""
    if any(t in title for t in STRONG_MARKET):
        return True
    if any(t in title for t in NOT_MARKET):
        return False
    has_company = any(c in title or c in lede for c in COMPANIES)
    if has_company and any(act in title or act in lede for act in BUSINESS_ACTS):
        return True
    if sum(1 for t in STRONG_MARKET if t in lede) >= 2:
        return True
    return False


def norm_title(t: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", t)


STOPWORDS = {"그리고", "하지만", "이번", "오늘", "지금", "결국", "대한", "위한", "관련", "이같",
             "있다", "있다는", "한다", "했다", "된다", "다는", "라는", "보다", "에서", "으로",
             "까지", "부터", "따라", "대해", "모두", "우리", "이날", "지난", "올해", "내년"}


def title_tokens(t: str) -> set:
    words = re.findall(r"[가-힣A-Za-z]{2,}", t)
    return {w for w in words if w not in STOPWORDS}


def is_near_duplicate(t: str, seen: list, seen_tokens: list) -> bool:
    """같은 사건을 살짝 바꿐 제목(다른 매체 중복)을 걸러낸다."""
    n = norm_title(t)
    if not n:
        return True
    toks = title_tokens(t)
    for s, st in zip(seen, seen_tokens):
        if n == s:
            return True
        k = min(len(n), len(s), 22)
        if k >= 12 and n[:k] == s[:k]:
            return True
        if len(n) > 10 and (n in s or s in n):
            return True
        if toks and st:
            inter = len(toks & st)
            if inter / max(1, len(toks | st)) >= 0.55:
                return True
    return False


# --------------------------------------------------------------------------- 대체 수집
def collect_google_news():
    """네이버 수집이 실패했을 때 쓰는 비상 경로 (Google 뉴스 RSS, API 키 불필요)."""
    queries = ["코스피 증시", "주식 상한가 특징주", "반도체 HBM 수주", "국내 증시 외국인 수급"]
    out = []
    for q in queries:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q) +
               "&hl=ko&gl=KR&ceid=KR:ko")
        try:
            xml = fetch(url)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] google rss failed ({q}): {e}", file=sys.stderr)
            continue
        for m in re.finditer(r"<item>(.*?)</item>", xml, re.S):
            block = m.group(1)
            t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.S)
            l = re.search(r"<link>(.*?)</link>", block, re.S)
            p = re.search(r"<pubDate>(.*?)</pubDate>", block, re.S)
            s = re.search(r"<source[^>]*>(.*?)</source>", block, re.S)
            if not (t and l):
                continue
            title = html_lib.unescape(re.sub(r"<[^>]+>", "", t.group(1))).strip()
            link = html_lib.unescape(l.group(1)).strip()
            press = html_lib.unescape(s.group(1)).strip() if s else ""
            if " - " in title:
                title, _, maybe_press = title.rpartition(" - ")
                press = press or maybe_press
            item = {
                "id": "g:" + link[-40:],
                "title": title,
                "lede": "",
                "press": press,
                "url": link,
                "section": "google",
                "weight": 0.6,
                "source": "google",
            }
            if p:
                try:
                    dt = parsedate_to_datetime(p.group(1).strip()).astimezone(KST)
                    item["time"] = dt.isoformat()
                except Exception:  # noqa: BLE001
                    pass
            out.append(item)
    print(f"[info] google fallback: {len(out)} items", file=sys.stderr)
    return out


# --------------------------------------------------------------------------- 메인
def build(out_path: str):
    raw = []
    for sid, name, weight in SECTIONS:
        raw.extend(parse_section(sid, name, weight))

    # 중복 제거 (같은 기사가 여러 섹션에 노출)
    merged = {}
    for a in raw:
        cur = merged.get(a["id"])
        if cur is None:
            merged[a["id"]] = a
        else:
            if a["weight"] > cur["weight"]:
                cur["weight"] = a["weight"]
                cur["section"] = a["section"]
            if len(a["lede"]) > len(cur.get("lede", "")):
                cur["lede"] = a["lede"]
            if not cur.get("press"):
                cur["press"] = a["press"]
    articles = list(merged.values())

    # 1차 분류·필터 (목록의 리드만으로 충분) → 관련 기사만 원문 조회해서 부하를 줄인다
    candidates = []
    seen_titles = []
    seen_tokens = []
    for a in articles:
        if not is_market_relevant(a):
            continue
        if is_near_duplicate(a["title"], seen_titles, seen_tokens):
            continue
        seen_titles.append(norm_title(a["title"]))
        seen_tokens.append(title_tokens(a["title"]))
        tid, tags, rel = classify(a)
        head = a["title"] + " " + a.get("lede", "")
        if rel < MIN_RELEVANCE and tid == "etc" and not any(t in head for t in MARKET_TERMS):
            continue
        a["theme"] = tid
        a["theme_label"] = THEME_LABEL.get(tid, "기타")
        a["tags"] = [t for t in tags if t != a["title"]][:3]
        a["relevance"] = rel
        candidates.append(a)
    candidates.sort(key=lambda a: -a["relevance"])
    candidates = candidates[: ARTICLE_LIMIT]

    if len(candidates) < 12:
        print("[warn] not enough naver items, using google fallback", file=sys.stderr)
        seen_titles = {a["title"] for a in candidates}
        for g in collect_google_news():
            if g["title"] not in seen_titles:
                seen_titles.add(g["title"])
                tid, tags, rel = classify(g)
                g.update(theme=tid, theme_label=THEME_LABEL.get(tid, "기타"),
                         tags=tags[:3], relevance=rel)
                candidates.append(g)

    # 원문에서 정확한 발행 시각·본문 리드 보강 (동시 요청)
    with ThreadPoolExecutor(max_workers=ARTICLE_FETCH_WORKERS) as pool:
        list(pool.map(enrich, candidates))

    # 시각을 못 가져온 기사는 느린 속도로 한 번 더 시도 (서버 과부하·순간 오류 대비)
    missing = [a for a in candidates if not a.get("time") and a.get("source") != "google"]
    if missing:
        print(f"[info] retry time for {len(missing)} items", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(enrich, missing))
        print(f"[info] still missing: {sum(1 for a in missing if not a.get('time'))}", file=sys.stderr)

    kept = []
    for a in candidates:
        summary = make_summary(a.get("lede") or a.get("body_lead") or "")
        if not summary:
            summary = make_summary(a.get("body_lead", ""))
        a["summary"] = summary
        a.pop("lede", None)
        a.pop("body_lead", None)
        a.pop("weight", None)
        kept.append(a)

    # 시간 정보 없는 기사는 뒤로, 최신순 정렬
    def sort_key(a):
        return (a.get("time") or "", a.get("relevance", 0))

    kept.sort(key=sort_key, reverse=True)
    kept = kept[:MAX_ARTICLES]

    now = datetime.now(KST)
    # 테마별 건수
    counts = {}
    for a in kept:
        counts[a["theme"]] = counts.get(a["theme"], 0) + 1
    order = [t[0] for t in THEMES]
    themes = [{"id": tid, "label": THEME_LABEL[tid], "color": THEME_COLOR[tid], "count": counts.get(tid, 0)}
              for tid in order if counts.get(tid)]
    themes.sort(key=lambda t: -t["count"])
    etc = counts.get("etc")
    if etc:
        themes.append({"id": "etc", "label": "기타", "color": "#9aa4b2", "count": etc})

    payload = {
        "generated_at": now.isoformat(),
        "generated_at_kst": now.strftime("%Y.%m.%d %H:%M"),
        "count": len(kept),
        "themes": themes,
        "articles": [{k: a[k] for k in ("id", "title", "summary", "press", "time", "url",
                                        "theme", "theme_label", "tags", "section", "relevance")
                      if k in a} for a in kept],
    }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"[done] {len(kept)} articles -> {out_path}", file=sys.stderr)
    return payload


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/news.json")
    args = ap.parse_args()
    build(args.out)
