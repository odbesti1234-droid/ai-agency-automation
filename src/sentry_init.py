"""Sentry SDK 초기화 — 한 곳에서 정의, 진입점들에서 import.

특징:
    - SENTRY_DSN 환경변수 없으면 silent disable (sentry_sdk.init(dsn="") OK)
    - FastApiIntegration + HttpxIntegration → 모든 외부 API 호출 자동 캡처
    - traces_sample_rate=0.1 (성능 트레이스 10%만)
    - environment·release Railway 환경변수 자동 사용
    - 중복 init() 방지 — 모듈 import 시 1회만 실행

진입점에서 사용:
    from src.sentry_init import init_sentry
    init_sentry()  # idempotent

except 절에서 직접 캡처:
    import sentry_sdk
    try: ...
    except Exception as e:
        sentry_sdk.capture_exception(e)
        ...
"""
from __future__ import annotations

import os
import sys

_INITIALIZED = False


def init_sentry() -> bool:
    """Sentry SDK init. DSN 없으면 silent skip. 호출 idempotent.

    Returns:
        True = 활성화됨 (DSN 있고 init 완료), False = silent disable
    """
    global _INITIALIZED
    if _INITIALIZED:
        return True

    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        # silent disable — DSN 안 박혀있어도 앱이 죽지 않음.
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.httpx import HttpxIntegration
    except ImportError as e:
        print(f"[sentry_init] sentry-sdk import 실패 — pip install sentry-sdk[fastapi,httpx] 필요: {e}", file=sys.stderr)
        return False

    environment = (
        os.environ.get("SENTRY_ENV")
        or os.environ.get("RAILWAY_ENVIRONMENT_NAME")
        or os.environ.get("RAILWAY_ENVIRONMENT")
        or "production"
    )
    release = (
        os.environ.get("SENTRY_RELEASE")
        or os.environ.get("RAILWAY_GIT_COMMIT_SHA")
        or "unknown"
    )

    sentry_sdk.init(
        dsn=dsn,
        integrations=[
            FastApiIntegration(),
            HttpxIntegration(),
        ],
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0.1")),
        environment=environment,
        release=release,
        send_default_pii=False,  # PII 안 보냄 (BotToken·매물 정보 등)
        # 운영 안정성 — 외부 라이브러리 noisy 로그 차단
        ignore_errors=[
            KeyboardInterrupt,
            SystemExit,
        ],
    )
    _INITIALIZED = True
    print(f"[sentry_init] ✅ initialized environment={environment} release={release[:8]}", flush=True)
    return True


def capture(exc: Exception, extra: dict | None = None) -> None:
    """except 절에서 호출. Sentry 활성화 안 되어 있으면 silent."""
    if not _INITIALIZED:
        return
    try:
        import sentry_sdk
        if extra:
            with sentry_sdk.push_scope() as scope:
                for k, v in extra.items():
                    scope.set_extra(k, v)
                sentry_sdk.capture_exception(exc)
        else:
            sentry_sdk.capture_exception(exc)
    except Exception:
        pass  # Sentry 자체 실패가 앱을 죽이면 안 됨
