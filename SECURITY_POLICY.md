# 보안 정책 (2026-04-19 수정)

## 1. API 자격증명 관리

### 원칙
- **민감한 API 토큰/키는 절대 DB에 저장하지 않음**
- 모든 외부 API 자격증명은 반드시 환경변수(`.env`)에서만 로드
- DB에는 공개 정보(클라이언트 ID, 슬러그, 이름 등)만 저장

### 환경변수 네이밍 규칙

#### 클라이언트별 자격증명
```
{CLIENT_SLUG_UPPER}_API_KEY
{CLIENT_SLUG_UPPER}_SECRET_TOKEN
{CLIENT_SLUG_UPPER}_IG_ACCESS_TOKEN    # Instagram
{CLIENT_SLUG_UPPER}_IG_ACCOUNT_ID      # Instagram
```

예시:
- `OEDO92_IG_ACCESS_TOKEN` — oedo92 클라이언트용 IG 액세스 토큰
- `FATHER_PLAN_B_IG_ACCOUNT_ID` — father_plan_b 클라이언트용 IG 계정 ID

#### 글로벌 자격증명 (fallback)
```
IG_ACCESS_TOKEN      # 기본값
IG_ACCOUNT_ID        # 기본값
ANTHROPIC_API_KEY    # 서버사이드 전용
OPENAI_API_KEY       # 서버사이드 전용
```

### 구현 패턴

```python
# ✅ 올바른 방식
slug_upper = client_slug.upper().replace("-", "_")
token = (
    os.environ.get(f"{slug_upper}_IG_ACCESS_TOKEN")
    or os.environ.get("IG_ACCESS_TOKEN", "")
)

# ❌ 절대 금지
token = client_row.get("ig_access_token")  # DB에서 읽음 - 금지!
```

---

## 2. DB 접근 제어 (RLS)

클라이언트 관련 테이블의 민감 컬럼:
- `ig_access_token` — **없음** (DB에 저장 자체 금지)
- `ig_account_id` — **없음** (DB에 저장 자체 금지)
- `slack_channel_webhook` — RLS 활성화 (L1+만 READ/UPDATE)

---

## 3. 환경변수 설정 가이드

### 로컬 개발 (`.env`)
```bash
# 글로벌 IG 자격증명
IG_ACCESS_TOKEN=your_global_ig_token
IG_ACCOUNT_ID=your_global_ig_id

# 클라이언트별 IG 자격증명
OEDO92_IG_ACCESS_TOKEN=oedo92_specific_token
OEDO92_IG_ACCOUNT_ID=oedo92_account_id

FATHER_PLAN_B_IG_ACCESS_TOKEN=father_plan_b_token
FATHER_PLAN_B_IG_ACCOUNT_ID=father_plan_b_account_id
```

### Vercel/Railway (프로덕션)
Vercel 환경변수 패널 또는 `railway variables set`으로 설정:
```bash
# 글로벌
IG_ACCESS_TOKEN=...
IG_ACCOUNT_ID=...

# 클라이언트별
OEDO92_IG_ACCESS_TOKEN=...
OEDO92_IG_ACCOUNT_ID=...
```

---

## 4. 코드 감사 체크리스트

### publisher.py 수정 이력
- **2026-04-19**: IG 토큰을 환경변수 전용으로 변경
  - 이전: `client_row.get("ig_access_token")` → DB에서 직접 읽음 (위험)
  - 현재: `os.environ.get(f"{slug_upper}_IG_ACCESS_TOKEN")` → 환경변수에서만 읽음 (안전)

### 정기 감사
```bash
# 1. DB에서 자격증명을 읽으려는 시도 검색
grep -r "\.get\(.*token\|\.get\(.*secret\|\.get\(.*key" src/agents --include="*.py" | grep -v "os.environ"

# 2. 하드코딩된 토큰 검색
grep -r "sk_live_\|sk_test_\|AIza\|ghp_" src/agents --include="*.py"

# 3. 클라이언트별 env 변수가 실제로 설정되어 있는지 확인
env | grep "IG_"
```

---

## 5. 배포 전 보안 체크리스트

1. [ ] `.env`에 민감 정보 포함 확인
2. [ ] `.gitignore`에 `.env*` 포함 확인
3. [ ] 소스코드에 하드코딩된 토큰 없음 확인
4. [ ] `client_row.get("*_token")` 같은 DB 직접 접근 없음 확인
5. [ ] Vercel/Railway 환경변수에 클라이언트별 토큰 설정됨 확인

---

## 6. 긴급 처치 (토큰 유출 시)

1. **즉시 토큰 폐지** — Instagram Graph API 또는 해당 서비스에서 토큰 삭제/로테이션
2. **새 토큰 발급** — 신규 토큰 생성
3. **환경변수 업데이트** — `.env` + Vercel/Railway 업데이트
4. **재배포** — `npx vercel deploy --prod --yes` 또는 `railway up`
5. **로그 검토** — GitHub History에 노출된 토큰 있는지 확인 (`git log -p | grep "token"`)
