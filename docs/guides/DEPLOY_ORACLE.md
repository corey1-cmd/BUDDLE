# Oracle Cloud VM 배포 런북 (베타 Phase 1)

스펙([android-beta-design §4 Phase 1](../superpowers/specs/2026-06-28-buddle-android-beta-design.md))의
백엔드 공개 배포 절차. **VM에 SSH 접속이 되는 순간부터** 이 문서를 따라가면
`https://<도메인>/health` 200까지 도달한다.

구성: `docker-compose.prod.yml` (api + redis + caddy) · `.env.production` · DB는 Supabase(외부).

---

## 0. 전제 (Phase 0에서 준비된 것)

- Oracle A1.Flex 인스턴스 (Ubuntu LTS, aarch64, 권장 4 OCPU / 24GB), 공인 IP, SSH 키
- Supabase 프로젝트 활성 상태 — **주의:** 과거 연결이 `tenant or user not found`로 실패한
  이력이 있다. 대시보드에서 프로젝트가 **일시정지(paused)** 상태가 아닌지 먼저 확인하고,
  Settings → Database에서 **pooler 연결 문자열**(aws-1-리전, 포트 6543)을 새로 복사할 것.
- Gemini API 키 (https://aistudio.google.com/apikey)

## 1. 방화벽 — 80/443만 개방

**Oracle 콘솔(필수):** VCN → Security List(또는 NSG)에 Ingress 규칙 추가
— TCP 80, TCP 443, UDP 443(HTTP/3, 선택). 22는 기본 존재.

**VM 내부(ufw):**

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw allow 443/udp
sudo ufw enable
```

> Oracle Ubuntu 이미지는 iptables에 기본 REJECT 규칙이 있는 경우가 있다.
> 80/443이 밖에서 안 열리면: `sudo iptables -L INPUT --line-numbers`로 REJECT보다
> 앞에 ACCEPT가 오도록 확인 (docker는 자체 체인을 쓰므로 대체로 무관).

## 2. Docker 설치 + 저장소 클론

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker

git clone https://github.com/corey1-cmd/BUDDLE.git && cd BUDDLE
```

## 3. 프로덕션 환경 파일

```bash
cp .env.production.example .env.production
openssl rand -hex 32   # → JWT_SECRET_KEY
openssl rand -hex 32   # → INTEGRITY_HMAC_KEY (반드시 위와 다른 값)
nano .env.production   # ★ 표시 항목 전부 채우기
```

★ 채울 값: `BUDDLE_DOMAIN`(`<공인IP>.sslip.io`), `DATABASE_URL`(Supabase pooler),
JWT/HMAC 키 2개, `PERSONA_ENDPOINT_API_KEY`(Gemini), `CORS_ORIGINS`/`WS_ALLOWED_ORIGINS`(도메인과 동일).

> `APP_ENV=production`이므로 dev 키/짧은 키/동일 키면 컨테이너가 뜨지 않고 즉시 종료된다
> — 로그에 이유가 찍힌다. 이는 의도된 fail-fast다.

## 4. 기동

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f api   # 첫 기동 관찰
```

첫 빌드/기동에서 오래 걸리는 두 지점(정상):

1. **이미지 빌드** — `INSTALL_EXTRAS="embeddings korean"`이 torch를 설치(ARM에서 수십 분 가능)
2. **첫 기동** — BGE-M3 모델 ~2GB 다운로드(`hfcache` 볼륨에 캐시되어 1회만)

빨리 먼저 띄우고 싶으면 `.env.production`에서 `EMBEDDING_PROVIDER=stub`로 시작한 뒤
나중에 `sentence_transformers`로 바꾸고 `docker compose ... up -d`만 다시 실행해도 된다
(기능 무중단, 검색 품질만 차이).

## 5. 검증 (스펙 Phase 1 기준)

```bash
# VM 밖(내 PC/폰 LTE)에서:
curl -s https://<BUDDLE_DOMAIN>/health          # {"status":"ok",...}
curl -s https://<BUDDLE_DOMAIN>/ready           # {"ready":true,...}  ← DB+Redis 연결 확인
```

- 브라우저로 `https://<BUDDLE_DOMAIN>/` → 로그인 화면(정적 웹) 표시
- 회원가입 → 로그인 → 피드 로딩 → 글 작성까지 눌러보기 (WSS 대화는 chat 화면에서)
- `/docs`는 production에서 비활성(404)이 **정상**

`/ready`가 `"postgres": "error: ..."`면 십중팔구 Supabase 쪽이다: 프로젝트 일시정지,
잘못된 pooler 리전, 비밀번호 특수문자 URL 인코딩(`@`→`%40` 등) 순으로 확인.

## 6. 시드 (선택 — 데모 계정/페르소나 모델)

```bash
docker compose -f docker-compose.prod.yml exec api python scripts/seed_persona_models.py
# 데모 계정까지 원하면 (베타 테스터 온보딩 전 임시):
docker compose -f docker-compose.prod.yml exec api python scripts/seed_dev_data.py
```

## 7. 운영 명령 모음

```bash
# 업데이트 배포 (git pull 후)
git pull && docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build

# 상태/로그
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f api

# 뉴스 수집 즉시 1회 (스케줄러는 1시간 주기 자동)
# admin 토큰 필요: scripts/make_admin.py로 내 계정 승격 후 로그인 토큰 사용
curl -X POST https://<도메인>/v1/admin/news/tick -H "Authorization: Bearer $ADMIN_TOKEN"

# 전체 중지 / 재시작
docker compose -f docker-compose.prod.yml down
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

## 8. 다음 단계

- 앱(Flutter)의 base URL을 `https://<BUDDLE_DOMAIN>`으로 설정 (Phase 3)
- 테스터가 늘면: Sentry DSN 설정(선택), `--profile observability`는 dev compose 전용이므로
  프로덕션 모니터링은 `/metrics` + 외부 스크레이퍼 또는 Sentry로.
