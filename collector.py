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




DAYS_LOOKBACK = int(os.environ.gt("DAYS_LOOKBACK", "1"))




# 메인 키워드 - 구문 검색 (따옴표 포함)
MAIN_KEYWORDS = [
    '"마인드카페"', '"마인드카페 센터"', '"마인드카페 상담센터"', '"마인드카페 EAP"',
