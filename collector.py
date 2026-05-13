#!/usr/bin/env python3
"""
News Bot Collector - 뉴스/블로그/카페/지식in/YouTube 수집 → Supabase 저장
GitHub Actions에서 실행됩니다.
"""

import os
import re
import json
import hashlib
import uuid
import urllib.parse
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
IGNORE_CACHE = os.environ.get("IGNORE_CACHE", "false").lower() == "true"

MAIN_KEYWORDS = [
    "마인드카페", "마인드카페 센터", "마인드카페 상담 센터", "마인드카페 EAP",
    "아토머스", "마인드비타", "마인드잇슈"
]
SUB_KEYWORDS = [
    "정신건강", "심리상담", "심리치료", "심리검사", "우울증", "ADHD",
    "놀이치료", "발달센터", "EAP", "마음건강"
]
YOUTUBE_KEYWORDS = ["마인드카페", "마인드비타", "마인드잇슈"]

MAX_ARTICLES_PER_KEYWORD = 8
MAX_BLOG_PER_KEYWORD = 5
MAX_YOUTUBE_PER_KEYWORD = 5

INCIDENT_KEYWORDS = [
    "사건", "사고", "체포", "구속", "기소", "재판", "판결", "수사", "범죄",
    "살인", "폭행", "성범죄", "성폭력", "마약", "음주운전", "뺑소니"
]
REGIONAL_KEYWORDS = [
    "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"
]

KST = timezone(timedelta(hours=9))


def clean_html(text):
    if not text:
        return ""
    text = unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def get_batch_id():
    now = datetime.now(KST)
    return now.strftime("%Y-%m-%d_%H:%M")


def tokenize_title(title):
    title = clean_html(title)
    title = re.sub(r"[^\w\s]", " ", title)
    tokens = [t.strip() for t in title.split() if len(t.strip()) >= 2]
    return tokens


def jaccard_similarity(tokens_a, tokens_b):
    if not tokens_a or not tokens_b:
        return 0.0
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def is_incident_title(title):
    return any(kw in title for kw in INCIDENT_KEYWORDS)


def is_regional_only(title):
    has_regional = any(region in title for region in REGIONAL_KEYWORDS)
    has_seoul = "서울" in title
    return has_regional and not has_seoul


def filter_article(title):
    title = clean_html(title)
    if is_incident_title(title):
        return True
    if is_regional_only(title):
        return True
    return False


def search_naver(query, search_type="news", display=10, start=1, sort="date"):
    url = f"https://openapi.naver.com/v1/search/{search_type}.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {"query": query, "display": display, "start": start, "sort": sort}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception as e:
        print(f"  [ERROR] Naver {search_type} search failed for '{query}': {e}")
        return []


def collect_naver_news(keyword, max_items=MAX_ARTICLES_PER_KEYWORD):
    items = search_naver(keyword, search_type="news", display=max_items)
    articles = []
    for item in items:
        title = clean_html(item.get("title", ""))
        if filter_article(title):
            continue
        articles.append({
            "title": title,
            "url": item.get("originallink") or item.get("link", ""),
            "description": clean_html(item.get("description", "")),
            "source_type": "naver_news",
            "publisher": item.get("publisher", ""),
            "published_at": item.get("pubDate"),
            "keyword": keyword,
        })
    return articles


def collect_naver_blog(keyword, max_items=MAX_BLOG_PER_KEYWORD):
    items = search_naver(keyword, search_type="blog", display=max_items)
    articles = []
    for item in items:
        title = clean_html(item.get("title", ""))
        articles.append({
            "title": title,
            "url": item.get("link", ""),
            "description": clean_html(item.get("description", "")),
            "source_type": "naver_blog",
            "publisher": item.get("bloggername", ""),
            "published_at": item.get("postdate"),
            "keyword": keyword,
        })
    return articles


def collect_naver_cafe(keyword, max_items=MAX_BLOG_PER_KEYWORD):
    items = search_naver(keyword, search_type="cafearticle", display=max_items)
    articles = []
    for item in items:
        title = clean_html(item.get("title", ""))
        articles.append({
            "title": title,
            "url": item.get("link", ""),
            "description": clean_html(item.get("description", "")),
            "source_type": "naver_cafe",
            "publisher": item.get("cafename", ""),
            "published_at": None,
            "keyword": keyword,
        })
    return articles


def collect_naver_kin(keyword, max_items=MAX_BLOG_PER_KEYWORD):
    items = search_naver(keyword, search_type="kin", display=max_items)
    articles = []
    for item in items:
        title = clean_html(item.get("title", ""))
        articles.append({
            "title": title,
            "url": item.get("link", ""),
            "description": clean_html(item.get("description", "")),
            "source_type": "naver_kin",
            "publisher": None,
            "published_at": None,
            "keyword": keyword,
        })
    return articles


def collect_youtube(keyword, max_items=MAX_YOUTUBE_PER_KEYWORD):
    if not YOUTUBE_API_KEY:
        print("  [WARN] YOUTUBE_API_KEY not set, skipping YouTube")
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
        print(f"  [ERROR] YouTube search failed for '{keyword}': {e}")
        return []
    articles = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        video_id = item.get("id", {}).get("videoId", "")
        title = snippet.get("title", "")
        description = snippet.get("description", "")
        channel = snippet.get("channelTitle", "")
        keyword_lower = keyword.lower()
        if not any(keyword_lower in text.lower() for text in [title, description, channel]):
            continue
        articles.append({
            "title": title,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "description": description[:500],
            "source_type": "youtube",
            "publisher": channel,
            "thumbnail_url": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
            "published_at": snippet.get("publishedAt"),
            "keyword": keyword,
        })
    return articles


def detect_duplicates(articles):
    for article in articles:
        article["title_tokens"] = tokenize_title(article["title"])
        article["duplicate_group_id"] = None
        article["is_duplicate_primary"] = True
    groups = []
    for i, article in enumerate(articles):
        tokens = article["title_tokens"]
        if not tokens:
            article["duplicate_group_id"] = str(uuid.uuid4())
            continue
        matched_group = None
        for group in groups:
            sim = jaccard_similarity(tokens, group["primary_tokens"])
            if sim >= 0.6:
                matched_group = group
                break
        if matched_group:
            article["duplicate_group_id"] = matched_group["group_id"]
            article["is_duplicate_primary"] = False
            matched_group["members"].append(i)
        else:
            gid = str(uuid.uuid4())
            article["duplicate_group_id"] = gid
            article["is_duplicate_primary"] = True
            groups.append({"group_id": gid, "primary_tokens": tokens, "members": [i]})
    dup_count = sum(1 for a in articles if not a["is_duplicate_primary"])
    return articles, dup_count


def save_to_supabase(supabase, articles, batch_id):
    saved = 0
    skipped = 0
    for article in articles:
        row = {
            "title": article["title"], "url": article["url"],
            "description": article.get("description"),
            "source_type": article["source_type"],
            "publisher": article.get("publisher"),
            "thumbnail_url": article.get("thumbnail_url"),
            "published_at": article.get("published_at"),
            "keyword": article["keyword"],
            "keyword_type": article.get("keyword_type", "main"),
            "collect_batch_id": batch_id,
            "duplicate_group_id": article.get("duplicate_group_id"),
            "is_duplicate_primary": article.get("is_duplicate_primary", True),
            "title_tokens": article.get("title_tokens", []),
            "status": "pending",
        }
        try:
            supabase.table("articles").upsert(row, on_conflict="url").execute()
            saved += 1
        except Exception as e:
            print(f"  [ERROR] Failed to save '{article['title'][:50]}': {e}")
            skipped += 1
    return saved, skipped


def main():
    print("=" * 60)
    print(f"News Bot Collector - {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    print(f"Lookback: {DAYS_LOOKBACK} days | Ignore cache: {IGNORE_CACHE}")
    print("=" * 60)
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    batch_id = get_batch_id()
    try:
        supabase.table("collect_batches").insert({"id": batch_id, "status": "running"}).execute()
    except Exception as e:
        print(f"[WARN] Could not create batch record: {e}")
    all_articles = []
    total_filtered = 0
    print("\n[1/3] 메인 키워드 수집 (뉴스 + 블로그 + 카페 + 지식in)")
    for kw in MAIN_KEYWORDS:
        print(f"  키워드: {kw}")
        for collector, source_name in [
            (collect_naver_news, "뉴스"), (collect_naver_blog, "블로그"),
            (collect_naver_cafe, "카페"), (collect_naver_kin, "지식in"),
        ]:
            items = collector(kw)
            for item in items:
                item["keyword_type"] = "main"
            print(f"    {source_name}: {len(items)}건")
            all_articles.extend(items)
    print("\n[2/3] 서브 키워드 수집 (뉴스만)")
    for kw in SUB_KEYWORDS:
        print(f"  키워드: {kw}")
        items = collect_naver_news(kw)
        for item in items:
            item["keyword_type"] = "sub"
        print(f"    뉴스: {len(items)}건")
        all_articles.extend(items)
    print("\n[3/3] YouTube 수집")
    for kw in YOUTUBE_KEYWORDS:
        print(f"  키워드: {kw}")
        items = collect_youtube(kw)
        for item in items:
            item["keyword_type"] = "youtube"
        print(f"    YouTube: {len(items)}건")
        all_articles.extend(items)
    seen_urls = set()
    unique_articles = []
    for article in all_articles:
        url = article["url"]
        if url not in seen_urls:
            seen_urls.add(url)
            unique_articles.append(article)
    print(f"\n총 수집: {len(all_articles)}건 → URL 중복 제거 후: {len(unique_articles)}건")
    print("\n중복 탐지 (제목 유사도 분석)...")
    unique_articles, dup_count = detect_duplicates(unique_articles)
    print(f"  중복 의심 기사: {dup_count}건")
    print("\nSupabase 저장 중...")
    saved, skipped = save_to_supabase(supabase, unique_articles, batch_id)
    print(f"  저장: {saved}건 | 스킵(이미 존재): {skipped}건")
    try:
        supabase.table("collect_batches").update({
            "completed_at": datetime.now(KST).isoformat(),
            "total_collected": len(unique_articles),
            "total_duplicates": dup_count,
            "total_filtered": total_filtered,
            "status": "completed",
        }).eq("id", batch_id).execute()
    except Exception as e:
        print(f"[WARN] Could not update batch record: {e}")
    print(f"\n완료! 대시보드에서 {len(unique_articles)}건을 리뷰할 수 있습니다.")


if __name__ == "__main__":
    main()
