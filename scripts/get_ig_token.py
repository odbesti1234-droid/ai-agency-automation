"""Instagram OAuth 토큰 발급 헬퍼.

실행:
    cd ai-agency-automation
    .venv/Scripts/activate
    python scripts/get_ig_token.py

1단계: 브라우저에서 OAuth URL 열기
2단계: 리다이렉트된 URL의 code= 파라미터 붙여넣기
3단계: short-lived → long-lived 교환 + IG 계정 ID 출력
4단계: 출력된 값을 .env 및 railway variables set 에 붙여넣기
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import os
import urllib.parse

import httpx

APP_ID = os.environ.get("META_APP_ID", "")
APP_SECRET = os.environ.get("META_APP_SECRET", "")
REDIRECT_URI = "https://ai-agency-automation-production.up.railway.app/ig_callback"

_GRAPH = "https://graph.facebook.com/v21.0"


def main() -> None:
    if not APP_ID or not APP_SECRET:
        print("❌ .env에 META_APP_ID / META_APP_SECRET 없음")
        sys.exit(1)

    # 1단계: OAuth URL
    params = urllib.parse.urlencode({
        "client_id": APP_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": "instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement",
        "response_type": "code",
    })
    auth_url = f"https://www.facebook.com/v21.0/dialog/oauth?{params}"

    print("=" * 60)
    print("1단계: 아래 URL을 브라우저에서 열고 앱 권한 허용")
    print("=" * 60)
    print(auth_url)
    print()

    code = input("2단계: 리다이렉트 URL의 ?code= 값 붙여넣기: ").strip()
    if not code:
        print("❌ code 없음 — 종료")
        sys.exit(1)

    # short-lived token 교환
    print("\n3단계: Short-lived token 교환 중...")
    resp = httpx.get(
        f"{_GRAPH}/oauth/access_token",
        params={
            "client_id": APP_ID,
            "redirect_uri": REDIRECT_URI,
            "client_secret": APP_SECRET,
            "code": code,
        },
        timeout=30,
    )
    data = resp.json()
    if "error" in data:
        print(f"❌ Short-lived 교환 실패: {data['error'].get('message', data)}")
        sys.exit(1)
    short_token = data["access_token"]
    print(f"  Short-lived token: {short_token[:20]}...")

    # long-lived 교환
    print("\n4단계: Long-lived token (60일) 교환 중...")
    from src.utils.ig_token import exchange_long_lived, get_ig_account_id
    long_token, expires_in = exchange_long_lived(short_token)
    days = expires_in // 86400
    print(f"  Long-lived token: {long_token[:20]}... (유효: ~{days}일)")

    # IG 계정 ID 조회
    print("\n5단계: IG 비즈니스 계정 ID 조회 중...")
    try:
        ig_account_id = get_ig_account_id(long_token)
        print(f"  IG Account ID: {ig_account_id}")
    except Exception as e:
        print(f"  ⚠️ 계정 ID 자동 조회 실패: {e}")
        ig_account_id = input("  수동 입력 (IG 비즈니스 계정 ID): ").strip()

    print("\n" + "=" * 60)
    print("✅ 완료! 아래 값을 Claude에게 붙여넣으면 Railway 설정까지 자동 완료:")
    print("=" * 60)
    print(f"IG_ACCESS_TOKEN={long_token}")
    print(f"IG_ACCOUNT_ID={ig_account_id}")
    print()
    print("또는 특정 클라이언트 slug가 oedo92라면:")
    print(f"OEDO92_IG_ACCESS_TOKEN={long_token}")
    print(f"OEDO92_IG_ACCOUNT_ID={ig_account_id}")


if __name__ == "__main__":
    main()
