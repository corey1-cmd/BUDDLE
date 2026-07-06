"""테스트 환경 부트스트랩 — 사람이 눌러볼 수 있는 데모 데이터 한 번에.

seed_dev_data(계정 뼈대)와 달리, 이 스크립트는 **실행 중인 API를 실제 클라이언트처럼
호출**해 전체 파이프라인(백혈구 게이트 → 매개자 태깅 → 피드/알림)을 통과한 데이터를
만든다. 결과적으로 UI를 열면 바로 눌러볼 것이 있는 상태가 된다:

  - 계정 3개: admin@buddle.app(관리자 승격) / alice@buddle.app / bob@buddle.app
  - 페르소나 + 한국어 공개 글 6개(태그·트렌딩 소재)
  - 상호작용: 좋아요·댓글·저장 → 알림 미읽음 뱃지 생김
  - 뉴스 브리핑 5건(공공누리 정부 출처 1건 포함) + 종합 다이제스트 → Redis 직접 주입
    (외부 RSS 호출 없이 뉴스 화면·인용 추천이 동작)
  - 위치 매칭: alice(서울) / bob(인천) 위치 공유 → 근처 화면에 매칭 등장

멱등: 재실행해도 계정은 재사용(로그인), 글/반응은 중복 생성될 수 있으나 데모 목적상 무해.

사용:
    # 1) 서비스 기동 (docker 또는 로컬)
    docker compose up -d          # 또는: uv run uvicorn buddle.main:app
    # 2) 시드
    uv run python scripts/seed_test_env.py [--base http://localhost:8000]

끝나면 계정/URL/관리자 토큰과 중앙관리자 API 예시 curl을 출력한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import httpx

ADMIN = ("admin@buddle.app", "Admin123!Admin")
ALICE = ("alice@buddle.app", "Alice123!Alice")
BOB = ("bob@buddle.app", "Bob12345!Bob")

POSTS_ALICE = [
    "전세 제도 개편 논의가 뜨겁습니다. 보증금 반환 보증을 의무화하면 임차인 보호가 되지만, 임대인 부담 전가로 월세 전환이 빨라질 수 있다는 반론도 있어요. 여러분 생각은 어떠세요?",
    "동네 하천 산책로에 야간 조명이 생기면서 저녁 운동 인구가 늘었어요. 작은 인프라 하나가 생활 패턴을 바꾸는 걸 보면, 지역 예산의 우선순위 논의가 더 활발해져야 한다고 느낍니다.",
    "AI 글쓰기 도구가 확산되면서 '진짜 내 생각'의 경계가 궁금해졌습니다. 도구가 문장을 다듬는 것과 생각을 대신하는 것 사이, 어디까지가 건강한 사용일까요?",
]
POSTS_BOB = [
    "반도체 수출 통계를 보면 메모리 편중이 여전합니다. 시스템 반도체 생태계를 키우려면 팹리스 지원과 함께 수요 기업 연결이 관건이라고 봅니다.",
    "지역 도서관의 코워킹 공간 전환 실험이 흥미롭습니다. 조용한 열람실과 협업 공간의 균형을 어떻게 잡을지가 쟁점이 될 것 같아요.",
    "출퇴근 시간대 버스 전용차로 연장 논의 — 승용차 정체가 늘어난다는 반대와 대중교통 정시성이 개선된다는 찬성이 팽팽합니다. 데이터 기반으로 구간별 판단이 필요해 보입니다.",
]

# 뉴스 브리핑(권리엔진 시연): 정부(공공누리) 1건 + 언론 티저 4건.
# 실제 기사 본문이 아니라 '우리 말 요약' 형태의 데모 데이터다.
NEWS_BRIEFINGS = [
    {
        "url": "https://www.korea.kr/news/policyNewsView.do?newsId=DEMO01",
        "title": "청년 전세보증금 반환보증 보증료 지원 확대",
        "source": "대한민국 정책브리핑",
        "gist_ko": "정부가 청년층 전세보증금 반환보증 보증료 지원 대상을 확대한다고 발표했다.",
        "tags": ["전세", "청년", "정책"],
        "relevance": 0.9,
        "stub": False,
    },
    {
        "url": "https://www.bbc.com/news/demo-ai-regulation",
        "title": "EU, AI 규제 이행 지침 초안 공개",
        "source": "BBC",
        "gist_ko": "EU 집행위가 AI법 이행을 위한 세부 지침 초안을 공개하고 의견 수렴에 들어갔다.",
        "tags": ["AI", "규제", "유럽"],
        "relevance": 0.8,
        "stub": False,
    },
    {
        "url": "https://www.theguardian.com/demo-semiconductor",
        "title": "글로벌 반도체 투자, 아시아 편중 심화",
        "source": "The Guardian",
        "gist_ko": "최근 1년간 반도체 설비 투자가 아시아 지역에 집중된 것으로 나타났다.",
        "tags": ["반도체", "투자", "경제"],
        "relevance": 0.8,
        "stub": False,
    },
    {
        "url": "https://www.theverge.com/demo-transit",
        "title": "대도시 대중교통 우선 정책, 통근 패턴 바꿨다",
        "source": "The Verge",
        "gist_ko": "버스 전용차로와 신호 우선 정책이 통근 시간대 이동 패턴을 바꾸고 있다는 분석.",
        "tags": ["교통", "도시", "정책"],
        "relevance": 0.7,
        "stub": False,
    },
    {
        "url": "https://arstechnica.com/demo-writing-ai",
        "title": "AI 글쓰기 도구 사용 실태 조사",
        "source": "Ars Technica",
        "gist_ko": "직장인 상당수가 문서 작성에 AI 도구를 쓰지만 최종 판단은 사람이 한다고 답했다.",
        "tags": ["AI", "글쓰기", "도구"],
        "relevance": 0.7,
        "stub": False,
    },
]

NEWS_DIGEST = {
    "text": "오늘의 흐름: 전세 보증 지원 확대 등 주거 정책이 이어지는 가운데, AI 규제 이행과 "
    "글쓰기 도구 확산 논의가 함께 진행 중. 반도체 투자 아시아 편중과 대중교통 우선 정책의 "
    "효과 분석도 주목할 만하다.",
    "tags": ["전세", "AI", "반도체", "교통"],
    "count": 5,
}


class Client:
    def __init__(self, base: str) -> None:
        self.http = httpx.Client(base_url=base, timeout=30)
        self.token: str | None = None

    def _h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def signup_or_login(self, email: str, password: str) -> None:
        r = self.http.post(
            "/v1/auth/signup",
            json={"email": email, "password": password, "password_confirm": password},
        )
        if r.status_code not in (201, 409):
            # 409/이미존재 외 오류는 실패로 처리
            r.raise_for_status()
        r = self.http.post("/v1/auth/login", json={"email": email, "password": password})
        r.raise_for_status()
        self.token = r.json()["access_token"]

    def ensure_persona(self, name: str) -> str:
        r = self.http.get("/v1/personas", headers=self._h())
        r.raise_for_status()
        for p in r.json():
            if p["name"] == name:
                return str(p["id"])
        models = self.http.get("/v1/persona-models", headers=self._h()).json()
        key = models[0].get("template_key") or models[0].get("model_key") or "poet"
        r = self.http.post("/v1/personas", json={"name": name, "model_key": key}, headers=self._h())
        r.raise_for_status()
        return str(r.json()["id"])

    def post(self, persona_id: str, content: str) -> str:
        r = self.http.post(
            "/v1/posts",
            json={"persona_id": persona_id, "content_raw": content, "visibility": "public"},
            headers=self._h(),
        )
        r.raise_for_status()
        return str(r.json()["id"])

    def like(self, post_id: str) -> None:
        self.http.put(f"/v1/plaza/posts/{post_id}/like", headers=self._h())

    def bookmark(self, post_id: str) -> None:
        self.http.put(f"/v1/plaza/posts/{post_id}/bookmark", headers=self._h())

    def comment(self, post_id: str, content: str, kind: str = "question") -> None:
        self.http.post(
            f"/v1/plaza/posts/{post_id}/comments",
            json={"content": content, "kind": kind},
            headers=self._h(),
        )

    def set_location(self, persona_id: str, lat: float, lon: float) -> None:
        self.http.put(
            f"/v1/proximity/personas/{persona_id}/location",
            json={"lat": lat, "lon": lon, "sharing": True},
            headers=self._h(),
        )


async def promote_admin(email: str) -> None:
    """DB 직접 승격 — 관리자 생성은 API로 불가(의도된 보안 설계)."""
    from sqlalchemy import select

    from buddle.db.models.user import User
    from buddle.db.session import AsyncSessionLocal, engine

    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            raise SystemExit(f"user not found for admin promotion: {email}")
        if not user.is_admin:
            user.is_admin = True
            await session.commit()
    await engine.dispose()


async def seed_news_redis() -> None:
    """뉴스 브리핑·다이제스트를 Redis에 직접 주입 (외부 RSS 없이 화면 동작)."""
    import redis.asyncio as aioredis

    from buddle.config import get_settings

    r = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    now = int(time.time())
    pipe = r.pipeline()
    pipe.delete("buddle:news:briefings")
    for i, b in enumerate(reversed(NEWS_BRIEFINGS)):
        item = {**b, "stored_at": now - i * 600, "ekb_briefing": ""}
        pipe.lpush("buddle:news:briefings", json.dumps(item, ensure_ascii=False))
    pipe.expire("buddle:news:briefings", 60 * 60 * 25)
    pipe.set(
        "buddle:news:digest",
        json.dumps({**NEWS_DIGEST, "ts": now}, ensure_ascii=False),
    )
    await pipe.execute()
    await r.aclose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    # 0) API 살아있나
    health = httpx.get(f"{base}/health", timeout=10)
    health.raise_for_status()

    # 1) 계정 3개
    admin, alice, bob = Client(base), Client(base), Client(base)
    admin.signup_or_login(*ADMIN)
    alice.signup_or_login(*ALICE)
    bob.signup_or_login(*BOB)

    # 2) 관리자 승격(DB) 후 재로그인(토큰에 최신 상태 반영은 불필요하지만 명확성)
    asyncio.run(promote_admin(ADMIN[0]))
    admin.signup_or_login(*ADMIN)

    # 3) 페르소나 + 글
    p_alice = alice.ensure_persona("초록")
    p_bob = bob.ensure_persona("바람")
    alice_posts = [alice.post(p_alice, t) for t in POSTS_ALICE]
    bob_posts = [bob.post(p_bob, t) for t in POSTS_BOB]

    # 4) 상호작용 → 알림 생성 (bob→alice 글, alice→bob 글)
    for pid in alice_posts[:2]:
        bob.like(pid)
        bob.bookmark(pid)
    bob.comment(alice_posts[0], "보증료 지원이 실제 전세→월세 전환 속도에 영향을 줄까요?")
    for pid in bob_posts[:2]:
        alice.like(pid)
    alice.comment(bob_posts[0], "팹리스 지원과 수요 연결, 구체적으로 어떤 정책이 효과적일까요?")
    alice.bookmark(bob_posts[2])

    # 5) 위치 매칭 (서울시청 / 인천시청 ≈ 27km → 4단계 '구·군')
    alice.set_location(p_alice, 37.5665, 126.9780)
    bob.set_location(p_bob, 37.4563, 126.7052)

    # 6) 뉴스 캐시 주입
    asyncio.run(seed_news_redis())

    # 7) 요약 출력
    print("\n" + "=" * 62)
    print("✅ 테스트 환경 준비 완료 —", base)
    print("=" * 62)
    print(
        f"""
┌ 계정 ──────────────────────────────────────────────
│ 관리자   {ADMIN[0]} / {ADMIN[1]}
│ 사용자A  {ALICE[0]} / {ALICE[1]}   (페르소나: 초록, 서울)
│ 사용자B  {BOB[0]} / {BOB[1]}   (페르소나: 바람, 인천)
├ 열어볼 화면 ────────────────────────────────────────
│ 피드(검색·트렌딩·저장)   {base}/feed.html
│ 알림(미읽음 뱃지)        {base}/notifications.html
│ 저장한 글                {base}/bookmarks.html
│ 관리자(중앙관리자 리포트) {base}/admin.html   ← 관리자 계정으로 로그인
│ API 문서(dev)            {base}/docs
├ 중앙관리자 API 예시 (ADMIN_TOKEN=관리자 access_token) ─
│ curl -H "Authorization: Bearer $ADMIN_TOKEN" {base}/v1/admin/monitor/report
│ curl -H "Authorization: Bearer $ADMIN_TOKEN" {base}/v1/admin/monitor/digest
│ curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" {base}/v1/admin/monitor/snapshot
│ curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" "{base}/v1/admin/monitor/autotune?apply=false"
└─────────────────────────────────────────────────────
ADMIN_TOKEN={admin.token}
"""
    )


if __name__ == "__main__":
    main()
