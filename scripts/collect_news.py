#!/usr/bin/env python3
"""국내 증시 뉴스 수집기 — 네이버 뉴스 경제 섹션(증권/산업/금융/글로벌경제/경제일반)에서
기사를 모아 테마 태그를 붙이고, 1~2줄 요약과 함께 data/news.json 으로 저장한다.

함께 만드는 것:
  · themes_rank — 테마별 기사 수·최근 6시간 비중·화제 기사·대표 키워드·최신 헤드라인과,
    공개 뉴스 패턴만으로 계산한 '단기 불씨 / 중기 흐름' 힌트와 그 근거 수치
  · schedules   — 제목·요약에서 일정·이벤트 단서(실적 발표, 금리 결정, IPO, 정책 시행 등)와
    시점 단서(내일/이번 주/날짜)를 함께 뽑아 주제별로 묶은 일정 카드

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
THEME_KWS = {tid: kws for tid, _l, _c, kws in THEMES}

# --------------------------------------------------------------------------- 흐름 힌트 사전
HOUR = timedelta(hours=1)

# 단기 집중·속보성 표현 (제목 기준)
BURST_WORDS = ("속보", "긴급", "급등", "급락", "폭등", "폭락", "쇼크", "붕괴", "상한가",
               "특징주", "패닉", "경고", "날벼락", "돌파", "폭발")
# 구조적 업황·정책 연속성 표현 (제목+요약 기준)
STRUCT_WORDS = ("업황", "정책", "규제", "장기", "구조", "사이클", "수출", "투자 확대", "지원",
                "육성", "공급망", "법안", "예산", "시행", "로드맵", "협약", "수주", "계약",
                "연속", "업계", "산업")
# 대표 키워드에서 빼는 너무 흔한 말
GENERIC_KEYWORDS = {"주가", "종목", "시장", "기업", "투자", "공시", "테마주", "특징주",
                    "급등", "급락", "상한가"}
# 같은 개념의 키워드가 둘 다 뽑히지 않도록 하나로 묶는다
KEYWORD_ALIAS = {"AI": "인공지능", "피지컬AI": "피지컬 AI", "2차전지": "이차전지"}

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


# --------------------------------------------------------------------------- 테마 순위·흐름 힌트
def to_dt(iso: str):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def theme_keywords(theme_id: str, arts: list, limit: int = 4):
    """테마 기사들에서 실제로 반복 등장한 키워드만 뽑는다 (빈도 기준, 추정 없음)."""
    score = {}
    for kw, _w in THEME_KWS.get(theme_id, []):
        if kw in GENERIC_KEYWORDS:
            continue
        s = 0
        for a in arts:
            title = a.get("title", "")
            summ = a.get("summary") or ""
            tags = a.get("tags") or []
            if kw in title:
                s += 3
            elif kw in tags:
                s += 2
            elif kw in summ:
                s += 1
        if s:
            score[kw] = s
    picked, picked_canon = [], set()
    for kw, _s in sorted(score.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0])):
        canon = KEYWORD_ALIAS.get(kw, kw)
        if canon in picked_canon or any(kw in p or p in kw for p in picked):
            continue
        picked.append(kw)
        picked_canon.add(canon)
        if len(picked) >= limit:
            break
    return picked


def flow_pool_from_articles(arts: list):
    pool = []
    for a in arts:
        t = to_dt(a.get("time"))
        if not t:
            continue
        title = a.get("title", "")
        full = title + " " + (a.get("summary") or "")
        pool.append((t, a.get("press", ""),
                     1 if (a.get("relevance") or 0) >= 14 else 0,
                     1 if any(w in full for w in STRUCT_WORDS) else 0,
                     1 if any(w in title for w in BURST_WORDS) else 0))
    return pool


def flow_hint(pool: list, now: datetime, count: int = 0):
    """공개 뉴스 패턴만으로 '단기 불씨' / '중기 흐름'을 가른다.
    pool = (보도시각, 매체, 화제, 구조적 표현, 속보성 표현) 튜플 목록 (최근 24시간 이력)."""
    n = len(pool)
    if not n:
        return {"type": "short", "label": "단기 불씨", "reason": "보도 시각 정보가 없어 흐름을 가르지 못했습니다."}

    times = [p[0] for p in pool]
    t3 = now - 3 * HOUR
    t6 = now - 6 * HOUR
    n3 = sum(1 for t in times if t >= t3)
    n6 = sum(1 for t in times if t >= t6)
    span = (max(times) - min(times)).total_seconds() / 3600.0
    hours = len({t.strftime("%Y-%m-%d %H") for t in times})
    presses = {p[1] for p in pool if p[1]}
    hot = sum(p[2] for p in pool)
    struct = sum(p[3] for p in pool)
    burst = sum(p[4] for p in pool)

    # 단기: 최근 몇 시간에 몰리고 속보성 표현이 많은가
    short = 0
    short += 3 if n3 / n >= 0.6 else (2 if n3 / n >= 0.35 else (1 if n3 / n >= 0.2 else 0))
    short += 2 if span <= 3 else (1 if span <= 6 else 0)
    short += 1 if burst >= 2 else 0
    short += 1 if hot >= 3 else 0

    # 중기: 하루를 넘겨 이어지는 보도 폭 + 다수 매체 + 구조적 업황·정책 표현
    long_ = 0
    long_ += 2 if span >= 18 else (1 if span >= 12 else 0)
    long_ += 1 if hours >= 8 and span >= 8 else 0
    long_ += 1 if len(presses) >= 8 and span >= 8 else 0
    long_ += 1 if struct >= 3 and span >= 8 else 0
    long_ += 1 if n >= 12 and span >= 8 else 0

    ratio6 = round(n6 / n * 100)
    if short > long_:
        reason = f"최근 3시간 {n3}건 · 최근 6시간 {n6}건({ratio6}%) · 보도 폭 {span:.1f}시간 · 매체 {len(presses)}곳"
        if burst:
            reason += f" · 속보성 표현 {burst}건"
        return {"type": "short", "label": "단기 불씨", "reason": reason}
    reason = f"보도 폭 {span:.1f}시간 · {hours}개 시간대 · 매체 {len(presses)}곳 · 24시간 {n}건 · 최근 6시간 {n6}건({ratio6}%)"
    if struct:
        reason += f" · 업황·정책 표현 {struct}건"
    return {"type": "medium", "label": "중기 흐름", "reason": reason}


HISTORY_HOURS = 26
HISTORY_MAX_ROWS = 1600


def load_history(path: str):
    """직전 실행이 data/news.json 에 남긴 테마별 24시간 보도 기록을 읽는다."""
    try:
        with open(path, encoding="utf-8") as f:
            prev = json.load(f)
        hist = prev.get("history")
        return hist if isinstance(hist, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def update_history(old: dict, kept: list, now: datetime):
    """기사 id 기준으로 중복 없이 합쳐 26시간까지만 남긴다 (기사는 공개 뉴스 메타뿐)."""
    cutoff = (now - timedelta(hours=HISTORY_HOURS)).strftime("%Y-%m-%dT%H")
    out = {}
    for tid, rows in (old or {}).items():
        if not isinstance(rows, list):
            continue
        clean = [r for r in rows if isinstance(r, list) and len(r) >= 6 and isinstance(r[1], str) and r[1] >= cutoff]
        if clean:
            out[tid] = clean

    for a in kept:
        tid = a.get("theme")
        if not tid or tid == "etc":
            continue
        t = to_dt(a.get("time")) or now
        hour = t.strftime("%Y-%m-%dT%H")
        if hour < cutoff:
            continue
        rows = out.setdefault(tid, [])
        rid = a.get("id") or a.get("url")
        if any(r[0] == rid for r in rows):
            continue
        full = a.get("title", "") + " " + (a.get("summary") or "")
        rows.append([rid, hour, (a.get("press") or "")[:20],
                     1 if (a.get("relevance") or 0) >= 14 else 0,
                     1 if any(w in full for w in STRUCT_WORDS) else 0,
                     1 if any(w in a.get("title", "") for w in BURST_WORDS) else 0])

    # 너무 커지지 않게 오래된 기록부터 덜어낸다
    total = sum(len(v) for v in out.values())
    if total > HISTORY_MAX_ROWS:
        flat = [(r[1], tid, r) for tid, rows in out.items() for r in rows]
        flat.sort(key=lambda x: x[0])
        drop = set(id(r) for _h, _t, r in flat[: total - HISTORY_MAX_ROWS])
        for tid in list(out):
            out[tid] = [r for r in out[tid] if id(r) not in drop]
            if not out[tid]:
                del out[tid]
    return out


def build_themes_rank(kept: list, now: datetime, history: dict | None = None):
    """기사 수 기준 테마 순위 + 흐름 힌트 (기타 테마는 순위에서 뺀다)."""
    history = history or {}
    by_theme = {}
    for a in kept:
        if a.get("theme") == "etc":
            continue
        by_theme.setdefault(a["theme"], []).append(a)

    rows = []
    for tid, arts in by_theme.items():
        arts = sorted(arts, key=lambda a: a.get("time") or "", reverse=True)
        times = [t for t in (to_dt(a.get("time")) for a in arts) if t]
        span = round((max(times) - min(times)).total_seconds() / 3600.0, 1) if len(times) > 1 else 0.0
        n6, hot = 0, 0

        # 24시간 보도 기록이 있으면 그것으로 흐름을 가르고, 없으면 이번 수집분만 쓴다
        hist = history.get(tid) or []
        pool = []
        for r in hist:
            t = datetime.strptime(r[1], "%Y-%m-%dT%H").replace(tzinfo=KST)
            pool.append((t, r[2], r[3], r[4], r[5]))
        hint_pool = pool if len(pool) >= len(arts) else flow_pool_from_articles(arts)
        day_n = len(hint_pool)
        day_presses = len({p[1] for p in hint_pool if p[1]})
        # 표시 수치와 힌트 판정이 같은 24시간 기록을 쓰도록 맞춘다
        pool_times = [p[0] for p in hint_pool]
        n6 = sum(1 for t in pool_times if t >= now - 6 * HOUR)
        hot = sum(p[2] for p in hint_pool)

        rows.append({
            "id": tid,
            "label": THEME_LABEL.get(tid, "기타"),
            "color": THEME_COLOR.get(tid, "#9aa4b2"),
            "count": len(arts),
            "recent_6h": n6,
            "recent_6h_ratio": round(n6 / day_n * 100) if day_n else 0,
            "day_count": day_n,
            "hot": hot,
            "presses": day_presses or len({a.get("press") for a in arts if a.get("press")}),
            "span_hours": span,
            "keywords": theme_keywords(tid, arts),
            "headlines": [{"title": a["title"], "url": a["url"], "press": a.get("press", ""),
                           "time": a.get("time", "")} for a in arts[:2]],
            "hint": flow_hint(hint_pool, now, count=len(arts)),
        })
    rows.sort(key=lambda r: (-r["count"], -r["hot"], -r["recent_6h"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


# --------------------------------------------------------------------------- 일정 뉴스
# 일정 종류: (id, 화면 라벨, 단서 표현) — 위에서부터 먼저 맞는 것을 쓴다
EVENT_TYPES = [
    ("rate", "금리 결정", ("금통위", "기준금리", "FOMC", "연준", "금리 인상", "금리 인하", "통화정책")),
    ("inflation", "물가·고용 지표", ("CPI", "소비자물가", "PPI", "고용보고서", "비농업", "물가지수")),
    ("earnings", "실적 발표", ("실적 발표", "실적발표", "잠정실적", "컨퍼런스콜", "어닝", "분기 실적",
                             "실적을 발표", "실적 시즌")),
    ("ipo", "IPO·공모", ("수요예측", "청약", "공모주", "IPO", "상장 예정", "상장을 앞", "입성",
                        "증권신고서")),
    ("shareholder", "주주총회·주주환원", ("주주총회", "임시주총", "사내이사", "배당락", "주주환원", "주총")),
    ("market", "증시 이벤트", ("동시만기", "옵션 만기", "MSCI", "리밸런싱", "주간 증시", "선물옵션")),
    ("event", "행사·시험", ("수능", "개최", "학회", "전시", "포럼", "박람회", "컨퍼런스", "개막")),
    ("policy", "정책·규제", ("시행령", "시행", "국무회의", "국회 통과", "법안", "예산안", "규제",
                           "지원책", "특별법", "공청회")),
    ("contract", "수주·계약", ("수주", "공급계약", "납품", "MOU", "협약", "계약 체결")),
]

# 일정 주제로 쓸 대상 이름 (제목에 나오면 '대상 + 일정명'으로 묶는다)
SUBJECTS = {
    "엔비디아": "엔비디아", "삼성전자": "삼성전자", "SK하이닉스": "SK하이닉스", "삼전닉스": "삼성전자·SK하이닉스",
    "삼성": "삼성", "한국은행": "한국은행", "한은": "한국은행", "금통위": "한국은행 금통위",
    "연준": "미 연준", "FOMC": "미 연준", "미국": "미국", "중국": "중국", "국회": "국회", "정부": "정부",
    "금융위": "금융위", "MSCI": "MSCI", "코스피": "코스피", "코스닥": "코스닥",
    "TSMC": "TSMC", "애플": "애플", "테슬라": "테슬라", "마이크로소프트": "마이크로소프트",
    "아마존": "아마존", "메타": "메타", "앤트로픽": "앤트로픽", "오픈AI": "오픈AI",
    "현대차": "현대차", "한화": "한화", "두산": "두산", "LG": "LG", "셀트리온": "셀트리온",
    "에코프로": "에코프로", "포스코": "포스코", "네이버": "네이버", "카카오": "카카오",
}

FUTURE_VERBS = ("예정", "예정이다", "개최된다", "개최될", "발표한다", "발표될", "열린다", "공개한다",
                "출시한다", "시행된다", "나선다", "앞두", "예고", "계획이다", "추진한다")
# 날짜 뒤에 붙어야 일정 날짜로 인정하는 말 (기사 작성일과 일정일을 가르기 위해)
DATE_CONTEXT = FUTURE_VERBS + ("발표", "개최", "만기", "청약", "수요예측", "상장", "출범", "시행",
                               "열리", "공개", "회의", "결정", "계약", "점검", "선고", "투표",
                               "총회", "모집", "입찰", "시험")
PAST_MARKERS = ("철회", "취소", "무산", "불발", "연기됐", "연기된다", "마감", "종료")

WEEKDAY_KR = ("월", "화", "수", "목", "금", "토", "일")


def _mk(y: int, m: int, d: int):
    try:
        return datetime(y, m, d, tzinfo=KST)
    except ValueError:
        return None


def _date_when(dt: datetime, ok_today: bool = False):
    return {"key": dt.date().isoformat(), "label": f"{dt.month}월 {dt.day}일 ({WEEKDAY_KR[dt.weekday()]})",
            "sort": dt.isoformat(), "date": dt.date().isoformat(), "ok_today": ok_today}


def resolve_when(text: str, pub: datetime, now: datetime):
    """시점 단서를 찾아 (정렬값, 표시 라벨, 묶음 키)를 돌려준다. 지난 시점·단서 없음은 None."""
    today = now.date()

    m = re.search(r"(\d{1,2})월\s*(\d{1,2})\s*[~∼\-–]\s*(\d{1,2})일", text)
    if m:
        mo, d1, d2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = pub.year if mo >= pub.month - 6 else pub.year + 1
        start, end = _mk(y, mo, d1), _mk(y, mo, d2)
        if start and end:
            if end.date() < today:
                return None
            return {"key": f"range-{start.date()}", "label": f"{mo}.{d1}~{d2}",
                    "sort": start.isoformat(), "date": start.date().isoformat()}

    m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", text)
    if m:
        dt = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dt:
            return _date_when(dt) if dt.date() >= today else None

    m = re.search(r"(\d{1,2})월\s*(\d{1,2})일", text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        y = pub.year if mo >= pub.month - 6 else pub.year + 1
        dt = _mk(y, mo, d)
        if dt:
            return _date_when(dt) if dt.date() >= today else None

    m = re.search(r"(?<![0-9거래영업근로])(\d{1,2})일(?!\s*(?:연속|만에|째|동안|간|만|전|후|새|차|분))", text)
    if m and "지난" not in text[max(0, m.start() - 3):m.start()]:
        tail = text[m.end():m.end() + 30]
        d = int(m.group(1))
        if any(w in tail for w in DATE_CONTEXT) and 1 <= d <= 31:
            dt = _mk(pub.year, pub.month, d)
            if dt is None or dt.date() < today - timedelta(days=15):
                nxt = (pub.replace(day=1) + timedelta(days=32)).replace(day=1)
                dt = _mk(nxt.year, nxt.month, d)
            if dt and dt.date() >= today:
                return _date_when(dt, ok_today=True)

    m = re.search(r"D-(\d{1,2})", text)
    if m:
        dt = pub + timedelta(days=int(m.group(1)))
        if dt.date() >= today:
            return _date_when(dt, ok_today=True)

    for word, days in (("모레", 2), ("내일", 1)):
        if word in text:
            return _date_when(pub + timedelta(days=days), ok_today=True)

    if re.search(r"이번\s*주|금주", text):
        return {"key": f"week-{pub.isocalendar()[:2]}", "label": "이번 주", "sort": pub.isoformat(), "date": None}
    if re.search(r"다음\s*주|차주", text):
        nx = pub + timedelta(days=7)
        return {"key": f"week-{nx.isocalendar()[:2]}", "label": "다음 주", "sort": nx.isoformat(), "date": None}

    if re.search(r"다음\s*달|월초|월말", text):
        nx = (pub.replace(day=1) + timedelta(days=32)).replace(day=1)
        return {"key": f"month-{nx.year}-{nx.month}", "label": "다음 달", "sort": nx.isoformat(), "date": None}
    if re.search(r"이번\s*달|이달", text):
        return {"key": f"month-{pub.year}-{pub.month}", "label": f"{pub.month}월 중", "sort": pub.isoformat(), "date": None}

    if "연내" in text:
        return {"key": f"year-{pub.year}", "label": "연내", "sort": pub.replace(month=12, day=31).isoformat(), "date": None}
    if "내년" in text:
        m = re.search(r"내년\s*(\d{1,2})월", text)
        mo = int(m.group(1)) if m else None
        base = datetime(pub.year + 1, mo or 1, 1, tzinfo=KST)
        label = f"내년 {mo}월" if mo else "내년"
        return {"key": f"nextyear-{mo}", "label": label, "sort": base.isoformat(), "date": None}
    m = re.search(r"([1-4])분기", text)
    if m:
        q = int(m.group(1))
        cur_q = (now.month - 1) // 3 + 1
        if q < cur_q:  # 지나간 분기 실적 기사는 일정이 아니다
            return None
        return {"key": f"q-{pub.year}-{q}", "label": f"{q}분기", "sort": pub.isoformat(), "date": None}
    return None


def detect_event(text: str):
    """일정 종류를 고른다. 앞쪽에 나온 표현일수록 우선하되, 구체적인 일정(금리·실적·IPO)을
    '주간 증시'·'개최' 같은 ñ은 표현보다 먼저 본다."""
    priority = {"rate": 4.0, "earnings": 3.5, "ipo": 3.0, "inflation": 3.0,
                "shareholder": 2.5, "policy": 2.0, "contract": 1.5, "market": 1.0, "event": 1.0}
    best = None
    for eid, label, kws in EVENT_TYPES:
        for kw in kws:
            pos = text.find(kw)
            if pos < 0:
                continue
            score = pos - 12 * priority.get(eid, 1.0)
            if best is None or score < best[0]:
                best = (score, pos, eid, label, kw)
    if best is None:
        return None
    return {"id": best[2], "label": best[3], "kw": best[4]}


SCHEDULE_QUERIES = (
    "금통위 기준금리 일정",
    "FOMC CPI 물가 발표",
    "실적 발표 일정",
    "IPO 수요예측 청약 상장",
    "공모주 청약 일정",
    "주주총회 배당 일정",
    "배당락 배당금 일정",
    "주간 증시 일정 전망",
    "코스피 주간 전망",
    "옵션 만기 MSCI 리밸런싱",
    "정책 시행 발표 증시",
    "국회 본회의 법안 처리",
)


def parse_kr_time(s: str, now: datetime):
    """다음 뉴스의 '4시간 전' 같은 표기를 실제 시각으로 바꾼다."""
    s = (s or "").strip()
    if not s:
        return None
    m = re.match(r"(\d+)\s*분\s*전", s)
    if m:
        return now - timedelta(minutes=int(m.group(1)))
    m = re.match(r"(\d+)\s*시간\s*전", s)
    if m:
        return now - timedelta(hours=int(m.group(1)))
    m = re.match(r"(\d+)\s*일\s*전", s)
    if m:
        return now - timedelta(days=int(m.group(1)))
    if s.startswith("어제"):
        return now - timedelta(days=1)
    if s.startswith("오늘") or "방금" in s:
        return now
    m = re.search(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", s)
    if m:
        dt = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dt:
            return dt
    m = re.search(r"(\d{1,2})월\s*(\d{1,2})일", s)
    if m:
        dt = _mk(now.year, int(m.group(1)), int(m.group(2)))
        if dt and dt.date() > now.date():
            dt = _mk(now.year - 1, int(m.group(1)), int(m.group(2)))
        return dt
    return None


def collect_daum_news(now: datetime):
    """일정 기사를 요약문까지 얻기 위한 다음 뉴스 검색 수집 (서버 렌더링 HTML)."""
    out, seen = [], set()
    for q in SCHEDULE_QUERIES:
        url = ("https://search.daum.net/search?w=news&sort=recency&q=" + urllib.parse.quote(q))
        try:
            page = fetch(url, timeout=15)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] daum search failed ({q}): {e}", file=sys.stderr)
            continue
        for chunk in page.split('<li data-docid="')[1:]:
            mt = re.search(r'<a[^>]*class="tit_main[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', chunk, re.S)
            if not mt:
                continue
            link = html_lib.unescape(mt.group(1))
            title = " ".join(html_lib.unescape(re.sub(r"<[^>]+>", "", mt.group(2))).split())
            if len(title) < 8:
                continue
            key = norm_title(title)
            if key in seen or any(is_near_duplicate(title, [k], [title_tokens(k)]) for k in list(seen)[:80]):
                continue
            md = re.search(r'<a[^>]*class="desc[^"]*"[^>]*>(.*?)</a>', chunk, re.S)
            desc = " ".join(html_lib.unescape(re.sub(r"<[^>]+>", "", md.group(1))).split()) if md else ""
            desc = re.sub(r"\s*….*$", "…", desc)
            mp = (re.search(r'<strong class="tit_item"[^>]*>\s*<span class="txt_info">(.*?)</span>', chunk, re.S)
                  or re.search(r'<strong class="tit_item"[^>]*title="([^"]+)"', chunk))
            press = html_lib.unescape(mp.group(1)).strip() if mp else ""
            mtm = re.search(r'<span class="txt_docinfo">([^<]*(?:전|어제|오늘)[^<]*)</span>', chunk)
            dt = parse_kr_time(mtm.group(1), now) if mtm else None
            if dt and dt < now - timedelta(days=4):
                continue
            seen.add(key)
            out.append({"id": "d:" + key[:28], "title": title, "summary": make_summary(desc, 140),
                        "press": press, "url": link, "source": "daum",
                        "time": (dt or now).isoformat()})
    print(f"[info] daum search: {len(out)} items", file=sys.stderr)
    return out


def collect_schedule_news(now: datetime):
    """일정 단서가 실린 기사를 넓게 모으기 위한 Google 뉴스 RSS 보조 수집 (API 키 불필요)."""
    out, seen = [], set()
    for q in SCHEDULE_QUERIES:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:3d") +
               "&hl=ko&gl=KR&ceid=KR:ko")
        try:
            xml = fetch(url, timeout=15)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] schedule rss failed ({q}): {e}", file=sys.stderr)
            continue
        for m in re.finditer(r"<item>(.*?)</item>", xml, re.S):
            block = m.group(1)
            mt = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.S)
            ml = re.search(r"<link>(.*?)</link>", block, re.S)
            mp = re.search(r"<pubDate>(.*?)</pubDate>", block, re.S)
            ms = re.search(r"<source[^>]*>(.*?)</source>", block, re.S)
            if not (mt and ml):
                continue
            title = html_lib.unescape(re.sub(r"<[^>]+>", "", mt.group(1))).strip()
            press = html_lib.unescape(ms.group(1)).strip() if ms else ""
            if " - " in title:
                title, _, tail = title.rpartition(" - ")
                press = press or tail.strip()
            while press and title.endswith(" - " + press):
                title = title[: -(len(press) + 3)].rstrip()
            key = norm_title(title)
            if not key or key in seen:
                continue
            seen.add(key)
            item = {"id": "g:" + key[:30], "title": title, "summary": "", "press": press,
                    "url": html_lib.unescape(ml.group(1)).strip(), "source": "google"}
            if mp:
                try:
                    item["time"] = parsedate_to_datetime(mp.group(1).strip()).astimezone(KST).isoformat()
                except Exception:  # noqa: BLE001
                    pass
            out.append(item)
    print(f"[info] schedule rss: {len(out)} items", file=sys.stderr)
    return out


def enrich_schedule_summaries(cards: list, now: datetime):
    """요약이 없는 일정 기사는 같은 제목의 다음 뉴스를 찾아 요약문을 붙인다 (최대 15건).
    제목이 사실상 같을 때만 쓰므로 다른 기사의 문장이 섞이지 않는다."""
    budget = 15
    for card in cards:
        for a in card["articles"]:
            if a.get("summary") or budget <= 0:
                continue
            budget -= 1
            try:
                page = fetch("https://search.daum.net/search?w=news&sort=recency&q=" +
                             urllib.parse.quote(a["title"]), timeout=12)
            except Exception:  # noqa: BLE001
                continue
            want = norm_title(a["title"])
            want_tok = title_tokens(a["title"])
            for chunk in page.split('<li data-docid="')[1:4]:
                mt = re.search(r'<a[^>]*class="tit_main[^"]*"[^>]*>(.*?)</a>', chunk, re.S)
                if not mt:
                    continue
                t2 = " ".join(html_lib.unescape(re.sub(r"<[^>]+>", "", mt.group(1))).split())
                n2, tok2 = norm_title(t2), title_tokens(t2)
                same = bool(n2) and (n2 == want or (want in n2 or n2 in want))
                near = bool(tok2) and len(want_tok & tok2) / max(1, len(want_tok | tok2)) >= 0.7
                if not (same or near):
                    continue
                md = re.search(r'<a[^>]*class="desc[^"]*"[^>]*>(.*?)</a>', chunk, re.S)
                if md:
                    desc = " ".join(html_lib.unescape(re.sub(r"<[^>]+>", "", md.group(1))).split())
                    desc = re.sub(r"\s*….*$", "…", desc)
                    sents = sentences(desc)
                    if len(sents) > 1 and len(sents[0]) < 12:  # 검색 미리보기의 잘린 첫 조각은 버린다
                        desc = " ".join(sents[1:-1] if len(sents) > 3 else sents[1:])
                    a["summary"] = make_summary(desc, 140)
                break
    return cards


def build_schedules(kept: list, now: datetime):
    """기사 제목·요약에서 일정 단서와 시점 단서가 함께 있는 것만 주제별로 묶는다."""
    pool = list(kept)
    try:
        extra = collect_daum_news(now) + collect_schedule_news(now)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] schedule collection failed: {e}", file=sys.stderr)
        extra = []
    have = {norm_title(a["title"]) for a in pool}
    have_titles, have_tokens = [], []
    for e in extra:
        k = norm_title(e["title"])
        if k in have or is_near_duplicate(e["title"], have_titles, have_tokens):
            continue
        have.add(k)
        have_titles.append(k)
        have_tokens.append(title_tokens(e["title"]))
        pool.append(e)

    groups = {}
    for a in pool:
        title = a["title"]
        summ = a.get("summary") or ""
        text = title + " " + summ
        if any(p in title for p in PAST_MARKERS):
            continue
        # 일정 종류는 제목에서만 판단한다 (요약문만 보고 종류를 정하면 기사와 무관한 일정이 생긴다)
        ev = detect_event(title)
        if not ev:
            continue
        # 검색으로 넓게 모은 기사는 증시와 무관한 행사·정치 뉴스를 걸러낸다
        if a.get("source") in ("daum", "google") and ev["id"] in ("event", "contract"):
            continue
        if a.get("source") == "daum" and not is_market_relevant({"title": title, "lede": summ}):
            continue
        pub = to_dt(a.get("time")) or now
        when = resolve_when(title, pub, now) or resolve_when(summ, pub, now)
        if not when:
            continue
        # 너무 먼 미래(30일 초과)는 단기 대시보드의 일정에서 빼둔다
        if when.get("date"):
            try:
                if datetime.fromisoformat(when["date"]).date() > (now + timedelta(days=30)).date():
                    continue
            except ValueError:
                pass
        # 오늘 날짜로 풀린 일정은 앞으로 할 일이라는 표현이 있을 때만 남긴다
        if (when.get("date") == now.date().isoformat() and not when.get("ok_today")
                and not any(v in text for v in FUTURE_VERBS)):
            continue
        subject = ""
        ev_pos = title.find(ev["kw"])
        best_dist = 10 ** 9
        for kw, disp in SUBJECTS.items():
            p = title.find(kw)
            if p < 0:
                continue
            if abs(p - ev_pos) < best_dist:
                best_dist, subject = abs(p - ev_pos), disp
        topic = f"{subject} {ev['label']}".strip() if subject else ev["label"]
        key = f"{ev['id']}|{when['key']}|{subject}"
        if os.environ.get("NEWS_DEBUG"):
            print(f"[debug] {when['label']:>12} | {topic} | {a.get('source','naver')} | {title[:60]}", file=sys.stderr)
        g = groups.setdefault(key, {"topic": topic, "type": ev["id"], "type_label": ev["label"],
                                   "when": when["label"], "date": when.get("date"),
                                   "sort": when["sort"], "articles": []})
        if len(g["articles"]) < 4 and all(x["title"] != title for x in g["articles"]):
            g["articles"].append({"title": title, "summary": summ, "press": a.get("press", ""),
                                  "time": a.get("time", ""), "url": a["url"]})

    cards = []
    for g in groups.values():
        if not g["articles"]:
            continue
        tid, _tags, _rel = classify({"title": g["articles"][0]["title"],
                                    "lede": g["articles"][0].get("summary", ""), "weight": 0.8})
        g["themes"] = [] if tid == "etc" else [{"id": tid, "label": THEME_LABEL[tid],
                                                 "color": THEME_COLOR[tid]}]
        g["count"] = len(g["articles"])
        g["source"] = ("google" if all(a["url"].startswith("https://news.google.com/") for a in g["articles"])
                       else "daum" if all(a["url"].startswith(("https://v.daum.net/", "http://v.daum.net/",
                                                                "https://cp.news.search.daum.net/"))
                                          for a in g["articles"]) else "naver")
        cards.append(g)
    cards.sort(key=lambda c: (c["sort"], -c["count"]))

    # 같은 주제가 여러 시점 카드로 중복되면 하나로 정리한다.
    # 구체적 날짜가 있는 카드를 우선하고, 날짜가 서로 다른 두 카드는 다른 일정으로 본다.
    def compat(a: str, b: str) -> bool:
        na, nb = re.sub(r"\s+", "", a), re.sub(r"\s+", "", b)
        return na == nb or na in nb or nb in na

    final = []

    def merge_into(dst, src):
        for a in src["articles"]:
            if len(dst["articles"]) >= 4:
                break
            if all(x["title"] != a["title"] for x in dst["articles"]):
                dst["articles"].append(a)
        dst["count"] = len(dst["articles"])

    for c in cards:
        prev = next((f for f in final if compat(f["topic"], c["topic"])), None)
        if prev is None:
            final.append(c)
            continue
        if prev.get("date") and not c.get("date"):
            merge_into(prev, c)
        elif c.get("date") and not prev.get("date"):
            final.remove(prev)
            merge_into(c, prev)
            final.append(c)
            if os.environ.get("NEWS_DEBUG"):
                print(f"[debug] replace {prev['when']} -> {c['when']} ({c['topic']})", file=sys.stderr)
        elif c.get("date") and prev.get("date") and c["date"] != prev["date"]:
            final.append(c)  # 서로 다른 날짜의 다른 일정
        else:
            merge_into(prev, c)

    final.sort(key=lambda c: (c["sort"], -c["count"]))
    print(f"[info] schedules: {len(groups)} groups -> {len(final)} cards", file=sys.stderr)
    return enrich_schedule_summaries(final[:10], now)


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
    history = update_history(load_history(out_path), kept, now)
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
        "themes_rank": build_themes_rank(kept, now, history),
        "schedules": build_schedules(kept, now),
        "history": history,
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
