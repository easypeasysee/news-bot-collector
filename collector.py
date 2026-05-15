#!/usr/bin/env python3
"""
News Bot Collector v2 - 데이터 추출 가이드 적용
구문 검색 + 스마트 필터링 + Supabase 저장
"""

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from html import unescape

import requests
from supabase import create_client

# ============================================
# 설정
# ============================================

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

DAYS_LOOKBACK = int(os.environ.get("DAYS_LOOKBACK", "5"))

# 메인 키워드 - 구문 검색 (따옴표 포함)
MAIN_KEYWORDS = [
    '"마인드카페"', '"마인드카페 센터"', '"마인드카페 상담센터"', '"마인드카페 EAP"',
    '"아토머스"', '"마인드비타"', '"마인드잇슈"'
]

# 서브 키워드 - 뉴스만
SUB_KEYWORDS = [
    "정신건강", "심리상담", "심리치료", "심리검사", "우울증", "ADHD",
    "놀이치료", "발달센터", "EAP", "마음건강"
]

# YouTube 키워드
YOUTUBE_KEYWORDS = ['"마인드카페"', '"마인드비타"']

MAX_ARTICLES_PER_KEYWORD = 10
MAX_BLOG_PER_KEYWORD = 5
MAX_YOUTUBE_PER_KEYWORD = 5

# 사건사고 제외 키워드
INCIDENT_KEYWORDS = [
    "사건", "사고", "체포", "구속", "기소", "재판", "판결", "수사", "범죄",
    "살인", "폭행", "성범죄", "성폭력", "마약", "음주운전", "뺑소니",
    "사망", "숨진", "피살", "방화", "절도", "사기"
]

# 서브키워드 인사이트 우선 키워드 (이 중 하나라도 포함되면 고품질 기사)
INSIGHT_KEYWORDS = [
    "정부", "통계", "발표", "법안", "개정", "정책", "제도",
    "EAP 도입", "근로자 지원", "기업 복지", "시장", "보고서", "트렌드",
    "연구", "조사", "설문", "예산", "지원사업", "국회",
    "건강보험", "수가", "보험 적용", "진흥원", "복지부"
]

# 놀이치료/발달센터 전용 서울 집중 키워드
LOCAL_FOCUS_KEYWORDS = ["놀이치료", "발달센터"]
LOCAL_FOCUS_TERMS = [
    "서울", "신규 개설", "개원", "오픈", "지자체", "지원 사업",
    "구청", "센터 설립", "위탁", "공모"
]

# 메인키워드 우선순위 키워드 (이용후기, 브랜드 추천)
BRAND_PRIORITY_KEYWORDS = [
    "후기", "이용후기", "추천", "상담후기", "솔직후기", "리뷰",
    "써봤", "사용해봤", "해봤는데", "괜찮", "좋았", "도움"
]

KST = timezone(timedelta(hours=9))


def clean_html(text):
    if not text:
        return ""
    text = unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def get_batch_id():
    return datetime.now(KST).strftime("%Y-%m-%d_%H:%M")


def tokenize_title(title):
    title = clean_html(title)
    title = re.sub(r"[^\w\s]", " ", title)
    return [t.strip() for t in title.split() if len(t.strip()) >= 2]


def jaccard_similarity(a, b):
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


def has_incident(title):
    return any(kw in title for kw in INCIDENT_KEYWORDS)


def has_insight(title, desc=""):
    text = title + " " + desc
    return any(kw in text for kw in INSIGHT_KEYWORDS)


def has_local_focus(title, desc=""):
    text = title + " " + desc
    return any(kw in text for kw in LOCAL_FOCUS_TERMS)


def has_brand_priority(title, desc=""):
    text = title + " " + desc
    return any(kw in text for kw in BRAND_PRIORITY_KEYWORDS)


def calc_priority(article, keyword_type):
    """기사 우선순위 점수 계산 (높을수록 좋음)"""
    score = 50
    title = article.get("title", "")
    desc = article.get("description", "")
    if keyword_type == "main":
        if has_brand_priority(title, desc):
            score += 30
    elif keyword_type == "sub":
        if has_insight(title, desc):
            score += 30
        if has_incident(title):
            score -= 100
    return score


# ============================================
# Naver API
# ============================================

def search_naver(query, search_type="news", display=10, sort="date"):
    url = f"https://openapi.naver.com/v1/search/{search_type}.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {"query": query, "display": display, "start": 1, "sort": sort}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception as e:
        print(f"  [ERROR] Naver {search_type} '{query}': {e}")
        return []


def collect_naver(keyword, search_type, keyword_type, max_items):
    type_map = {"news": "naver_news", "blog": "naver_blog", "cafearticle": "naver_cafe", "kin": "naver_kin"}
    items = search_naver(keyword, search_type=search_type, display=max_items)
    articles = []
    for item in items:
        title = clean_html(item.get("title", ""))
        desc = clean_html(item.get("description", ""))
        priority = calc_priority({"title": title, "description": desc}, keyword_type)

        # 서브키워드: 사건사고 완전 제외
        if keyword_type == "sub" and has_incident(title):
            continue

        # 서브키워드 중 놀이치료/발달센터: 서울/지자체 관련만
        clean_kw = keyword.replace('"', '')
        if keyword_type == "sub" and clean_kw in LOCAL_FOCUS_KEYWORDS:
            if not has_local_focus(title, desc):
                continue

        articles.append({
            "title": title,
            "url": item.get("originallink") or item.get("link", ""),
            "description": desc,
            "source_type": type_map.get(search_type, search_type),
            "publisher": item.get("publisher") or item.get("bloggername") or item.get("cafename"),
            "published_at": item.get("pubDate") or item.get("postdate"),
            "keyword": clean_kw,
            "keyword_type": keyword_type,
            "priority": priority,
        })
    return articles


# ============================================
# YouTube API
# ============================================

def collect_youtube(keyword, max_items=MAX_YOUTUBE_PER_KEYWORD):
    if not YOUTUBE_API_KEY:
        return []
    url = "https://www.googleapis.com/youtube/v3/search"
    published_after = (datetime.now(KST) - timedelta(days=DAYS_LOOKBACK)).isoformat()
    params = {
        "part": "snippet", "q": keyword, "type": "video", "order": "date",
        "maxResults": max_items, "publishedAfter": published_after, "key": YOUTUBE_API_KEY,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [ERROR] YouTube '{keyword}': {e}")
        return []
    articles = []
    clean_kw = keyword.replace('"', '')
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        vid = item.get("id", {}).get("videoId", "")
        title = snippet.get("title", "")
        desc = snippet.get("description", "")
        channel = snippet.get("channelTitle", "")
        kw_lower = clean_kw.lower()
        if not any(kw_lower in t.lower() for t in [title, desc, channel]):
            continue
        articles.append({
            "title": title,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "description": desc[:500],
            "source_type": "youtube",
            "publisher": channel,
            "thumbnail_url": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
            "published_at": snippet.get("publishedAt"),
            "keyword": clean_kw,
            "keyword_type": "youtube",
        })
    return articles


# ============================================
# 중복 탐지 & 저장
# ============================================

def detect_duplicates(articles):
    for a in articles:
        a["title_tokens"] = tokenize_title(a["title"])
        a["duplicate_group_id"] = None
        a["is_duplicate_primary"] = True
    groups = []
    for i, a in enumerate(articles):
        tokens = a["title_tokens"]
        if not tokens:
            a["duplicate_group_id"] = str(uuid.uuid4())
            continue
        matched = None
        for g in groups:
            if jaccard_similarity(tokens, g["tokens"]) >= 0.6:
                matched = g
                break
        if matched:
            a["duplicate_group_id"] = matched["id"]
            a["is_duplicate_primary"] = False
        else:
            gid = str(uuid.uuid4())
            a["duplicate_group_id"] = gid
            a["is_duplicate_primary"] = True
            groups.append({"id": gid, "tokens": tokens})
    return articles, sum(1 for a in articles if not a["is_duplicate_primary"])


def save_to_supabase(sb, articles, batch_id):
    saved = skipped = 0
    for a in articles:
        row = {
            "title": a["title"], "url": a["url"], "description": a.get("description"),
            "source_type": a["source_type"], "publisher": a.get("publisher"),
            "thumbnail_url": a.get("thumbnail_url"), "published_at": a.get("published_at"),
            "keyword": a["keyword"], "keyword_type": a.get("keyword_type", "main"),
            "collect_batch_id": batch_id,
            "duplicate_group_id": a.get("duplicate_group_id"),
            "is_duplicate_primary": a.get("is_duplicate_primary", True),
            "title_tokens": a.get("title_tokens", []),
            "status": "pending",
        }
        try:
            sb.table("articles").upsert(row, on_conflict="url").execute()
            saved += 1
        except Exception as e:
            print(f"  [ERROR] Save failed: {e}")
            skipped += 1
    return saved, skipped


# ============================================
# 메인
# ============================================

def main():
    print("=" * 60)
    print(f"News Bot Collector v2 - {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    print(f"Lookback: {DAYS_LOOKBACK} days")
    print("=" * 60)

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    batch_id = get_batch_id()
    try:
        sb.table("collect_batches").insert({"id": batch_id, "status": "running"}).execute()
    except:
        pass

    all_articles = []

    # 1. 메인 키워드 (뉴스+블로그+카페+지식in)
    print("\n[1/3] 메인 키워드 (구문 검색)")
    for kw in MAIN_KEYWORDS:
        print(f"  {kw}")
        for stype, label, mx in [
            ("news", "뉴스", MAX_ARTICLES_PER_KEYWORD),
            ("blog", "블로그", MAX_BLOG_PER_KEYWORD),
            ("cafearticle", "카페", MAX_BLOG_PER_KEYWORD),
            ("kin", "지식in", MAX_BLOG_PER_KEYWORD),
        ]:
            items = collect_naver(kw, stype, "main", mx)
            print(f"    {label}: {len(items)}건")
            all_articles.extend(items)

    # 2. 서브 키워드 (뉴스만, 스마트 필터)
    print("\n[2/3] 서브 키워드 (인사이트 필터)")
    for kw in SUB_KEYWORDS:
        items = collect_naver(kw, "news", "sub", MAX_ARTICLES_PER_KEYWORD)
        print(f"  {kw}: {len(items)}건")
        all_articles.extend(items)

    # 3. YouTube
    print("\n[3/3] YouTube")
    for kw in YOUTUBE_KEYWORDS:
        items = collect_youtube(kw)
        print(f"  {kw}: {len(items)}건")
        all_articles.extend(items)

    # URL 중복 제거
    seen = set()
    unique = []
    for a in all_articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)
    print(f"\n수집: {len(all_articles)}건 -> 중복제거: {len(unique)}건")

    # 중복 탐지
    unique, dup_count = detect_duplicates(unique)
    print(f"중복 의심: {dup_count}건")

    # 저장
    saved, skipped = save_to_supabase(sb, unique, batch_id)
    print(f"저장: {saved}건 | 스킵: {skipped}건")

    try:
        sb.table("collect_batches").update({
            "completed_at": datetime.now(KST).isoformat(),
            "total_collected": len(unique), "total_duplicates": dup_count,
            "status": "completed",
        }).eq("id", batch_id).execute()
    except:
        pass

    print(f"\n완료! 대시보드에서 리뷰하세요.")


if __name__ == "__main__":
    main()
