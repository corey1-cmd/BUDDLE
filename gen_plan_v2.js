const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, LevelFormat, HeadingLevel, BorderStyle, WidthType, ShadingType, PageBreak,
} = require("docx");

const FONT = "Malgun Gothic";
const INK = "1F2A33";
const ACCENT = "2E5AA8";
const OKC = "1E7A46";
const RUNC = "B06A00";
const CW = 9026; // A4 content width @ 1" margins

const bd = { style: BorderStyle.SINGLE, size: 1, color: "C9D2DE" };
const borders = { top: bd, bottom: bd, left: bd, right: bd };
const cm = { top: 80, bottom: 80, left: 120, right: 120 };

const h1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const h2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const para = (t, o = {}) => new Paragraph({ spacing: { after: 120, line: 300 }, children: [new TextRun({ text: t, ...o })] });
const bullet = (t, o = {}) => new Paragraph({ numbering: { reference: "b", level: 0 }, spacing: { after: 60, line: 290 }, children: [new TextRun({ text: t, ...o })] });

function rich(parts) { return new Paragraph({ spacing: { after: 120, line: 300 }, children: parts.map((p) => new TextRun(p)) }); }

function tc(text, { w, head = false, fill, color, bold } = {}) {
  const runs = Array.isArray(text)
    ? text.map((t) => new TextRun(t))
    : [new TextRun({ text: String(text), bold: bold || head, color: color || (head ? "FFFFFF" : INK) })];
  return new TableCell({
    borders, width: { size: w, type: WidthType.DXA }, margins: cm,
    shading: { fill: head ? ACCENT : (fill || "FFFFFF"), type: ShadingType.CLEAR },
    children: [new Paragraph({ children: runs })],
  });
}
function table(rows, widths, opts = {}) {
  return new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: widths,
    rows: rows.map((r, i) => new TableRow({
      children: r.map((c, j) => {
        if (c && typeof c === "object" && "text" in c) return tc(c.text, { w: widths[j], head: i === 0, fill: c.fill, color: c.color, bold: c.bold });
        return tc(c, { w: widths[j], head: i === 0 });
      }),
    })),
  });
}
const STAT = { done: { text: "완료", fill: "E3F2E9", color: OKC, bold: true }, prog: { text: "진행", fill: "FFF3DD", color: RUNC, bold: true }, plan: { text: "예정", fill: "EAEFF7", color: ACCENT, bold: true } };

const ch = [];

// Title
ch.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 }, children: [new TextRun({ text: "AI 위치기반 매칭 서비스", bold: true, size: 36, color: INK })] }));
ch.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 }, children: [new TextRun({ text: "사업 계획 및 인프라 지원 신청서", size: 26, color: INK })] }));
ch.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 }, children: [new TextRun({ text: "서비스명: buddle  ·  운영사: 메트리아(Metria)", size: 20, color: ACCENT })] }));
ch.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 }, children: [new TextRun({ text: "2026년 6월  ·  창업 2개월차 (창업일 2026년 4월)", size: 18, color: "777777" })] }));

// 1
ch.push(h1("1. 사업 개요"));
ch.push(para("본 서비스(buddle)는 AI가 사람과 사람 사이의 의사소통을 매개하여, 언어 장벽을 넘어 생각이 닿게 하는 위치기반 소셜 플랫폼이다. 사용자가 떠오르는 생각을 적으면 AI가 이를 다듬어 다국어로 게시·전달하고, 유사한 관심을 가진 가까운 사용자를 연결한다. 핵심 가치는 ‘AI가 사람을 분석·판정하지 않고, 콘텐츠의 의미 유사도로 자연스럽게 연결한다’는 점이다."));
ch.push(table([
  ["항목", "내용"],
  ["서비스명", "buddle (AI 매개 다국어·위치기반 소셜 플랫폼)"],
  ["운영사", "메트리아(Metria) · 사업자등록 585-03-03590"],
  ["창업일", "2026년 4월 (창업 2개월차)"],
  ["대상", "위치기반으로 주변 사용자와 연결을 원하는 일반 소비자"],
  ["핵심 기술", "자체 서버 구동 오픈소스 LLM(GLM, MIT) + 벡터 임베딩 매칭 + 위치 근접"],
], [2400, 6626]));

// 2 — 현재 개발 현황 (핵심 추가)
ch.push(h1("2. 현재 개발 현황"));
ch.push(para("핵심 플랫폼은 이미 구현·검증된 상태이며, 본 신청 단계의 과제는 ‘AI 모델 실연동’과 ‘인프라 확보’다. 현재까지의 산출물은 다음과 같다."));
ch.push(h2("2-1. 구현 완료 — 백엔드 (서버 핵심 로직)"));
ch.push(table([
  ["구성요소", "내용", "상태"],
  ["기반 아키텍처", "FastAPI + SQLAlchemy 2.0(async) + PostgreSQL 16 + pgvector + Redis (소스 164개 파일)", STAT.done],
  ["5-AI 권한분리 생태계", "페르소나·매개자·백혈구(윤리)·기술자(무결성)·중앙관리자 — 역할별 권한 분리", STAT.done],
  ["콘텐츠 인지(분석)", "규칙 기반 파이프라인. 외부/추가 LLM 호출 0회, 사용자 프로파일링 없음(편향·프라이버시 안전)", STAT.done],
  ["다국어 매개", "한국어↔영어 게시·전달 경로, 게시물 번역 구조", STAT.done],
  ["지식공간(Layer B)", "콘텐츠 임베딩 지식 단위 + 통찰 번들(InsightBundle) 종합 구조", STAT.done],
  ["위치 근접 매칭", "haversine 동심원 10단계 근접도 + 좌표 일반화(프라이버시)", STAT.done],
  ["대화 세션", "주제 기반 대화 세션 관리", STAT.done],
  ["인증·보안", "JWT(HS256)·argon2id·HMAC-SHA256, 레이트리밋·SSRF 방어·감사로그", STAT.done],
], [2200, 5526, 1300]));
ch.push(h2("2-2. 구현 완료 — 프론트엔드 (9개 화면)"));
ch.push(table([
  ["구성요소", "내용", "상태"],
  ["화면 9종", "로그인·홈·페르소나 선택·페르소나 생성·대화·글쓰기·피드·인박스·근처 매칭", STAT.done],
  ["디자인 시스템", "코스믹 라테 배경 + 파스텔/오로라 그라데이션 + 글래스모피즘 마감(다국어 친화 타이포)", STAT.done],
  ["프론트 보안", "security.js — XSS 이스케이프·CSP·클릭재킹 방어·입력 검증(인라인 내장)", STAT.done],
  ["API 연동 계층", "api.js — 백엔드 26개 경로와 정합 검증 완료, JWT 자동 갱신·WebSocket", STAT.done],
], [2200, 5526, 1300]));
ch.push(h2("2-3. 품질 검증 현황"));
ch.push(table([
  ["지표", "현황"],
  ["자동화 테스트", "319개 통과 (DB 환경 필요한 통합 테스트 62개는 인프라 확보 후 실행)"],
  ["정적 분석", "ruff(린트) + mypy(strict 타입검사, 164개 소스) 무결점 통과"],
  ["DB 마이그레이션", "0001~0015 (총 15개) 정의 완료"],
  ["보안 검토", "양자내성 검토 완료 — 앱 계층 대칭암호(HS256·argon2id·HMAC)는 양자 시대에도 안전, 전송계층은 PQC TLS 권고"],
], [2600, 6426]));
ch.push(h2("2-4. AI 통합 — 설계 완료, 연동 착수"));
ch.push(table([
  ["항목", "내용", "상태"],
  ["AI 통합 설계서", "역할별 모델 티어링·서빙·성능·편향계약 정합 설계 확정", STAT.done],
  ["모델 배선", "번역·종합 기본값 GLM-4.6 배선, 임베딩 차원 단일화(전환 1줄화)", STAT.done],
  ["서빙 정의", "vLLM 자체서버 docker-compose(GLM-4.6 + 임베딩 + DB + Redis), 외부 API 0", STAT.done],
  ["실모델 연동", "스텁 → 실모델 전환, 단일 경로 E2E 검증", STAT.prog],
], [2200, 5526, 1300]));

// 3
ch.push(new Paragraph({ children: [new PageBreak()] }));
ch.push(h1("3. 서비스 구성 및 핵심 기능"));
ch.push(h2("3-1. 핵심 기능 3가지"));
ch.push(table([
  ["기능", "설명", "AI 활용"],
  ["① 대화", "AI 페르소나와 자연어로 대화하며 생각을 정리·표현", "GLM-4.6이 따뜻한 한국어 대화·다국어 글 생성"],
  ["② 매개·번역", "다듬어진 생각을 공개/비공개로 게시하고 상대 언어로 전달", "GLM-4.6 번역(한↔영) + 매개자 AI 라우팅"],
  ["③ 매칭", "유사 관심 사용자를 위치 기반으로 연결", "콘텐츠 임베딩 유사도 + 위치 근접(프로파일링 없음)"],
], [1700, 3900, 3426]));
ch.push(h2("3-2. 시스템 아키텍처 (현재 구현 반영)"));
ch.push(bullet("사용자 앱(9화면) → API 게이트웨이(FastAPI) → 자체 GLM 추론 서버(vLLM, OpenAI 호환)"));
ch.push(bullet("대화·글·지식 → PostgreSQL 16 저장 / 콘텐츠 임베딩 → pgvector(동일 DB 내 벡터 검색)"));
ch.push(bullet("매칭 요청 → pgvector 코사인 유사도 + 위치 근접(haversine 동심원) → 결과 반환"));
ch.push(bullet("GLM은 외부 API 없이 사설망 내부에서 완전 구동 — 사용자 데이터 외부 유출 없음"));
ch.push(para("주: 벡터 검색은 별도 시스템 없이 PostgreSQL의 pgvector 확장으로 처리하여 운영 단순성·데이터 일관성을 확보(대규모 확장 시 전용 벡터 DB·PostGIS 검토).", { size: 18, color: "777777" }));

// 4
ch.push(h1("4. 기술 스택"));
ch.push(table([
  ["역할", "기술", "선택 이유 / 현황"],
  ["대화·번역·종합 LLM", "GLM-4.6 (MIT)", "한국어·소셜·창작 감정표현 공식 최적화, 자체 구동(배선 완료)"],
  ["심층 추론(선택)", "GLM-5.1 (754B, MIT)", "프런티어급 추론·장기 컨텍스트, 고난도 종합 배치(인프라 확보 시)"],
  ["추론 서버", "vLLM", "OpenAI 호환, FP8·연속배칭·speculative 고처리량(compose 작성 완료)"],
  ["백엔드", "FastAPI (async)", "비동기 고성능 — 구현 완료(164 파일, 테스트 319)"],
  ["DB / 벡터", "PostgreSQL 16 + pgvector", "관계형+벡터 단일 DB — 스키마·마이그레이션 완료"],
  ["임베딩", "ko-sroberta(768) → BGE-M3(1024)", "한국어 자체호스팅, 단계적 업그레이드(차원 단일화 완료)"],
  ["캐시·세션", "Redis", "레이트리밋·세션·임베딩 캐시"],
  ["위치", "haversine 근접(→ PostGIS)", "초기 경량 구현 완료, 확장 시 공간 인덱스"],
], [2200, 2700, 4126]));

// 5
ch.push(h1("5. AI 모델 선택 근거 (자체 서버 · 외부 API 미사용)"));
ch.push(para("작업 성격에 따라 모델을 티어링한다. 코딩 벤치마크 1위 모델이 곧 ‘따뜻한 한국어 소셜 글쓰기’ 1위는 아니라는 판단에 따라, 페르소나의 본질에 맞는 모델을 1차 워크호스로 두고 심층 추론용 플래그십을 별도 티어로 둔다. 어댑터가 프로토콜 기반이라 모델 교체가 자유롭다."));
ch.push(table([
  ["티어", "모델", "용도", "근거"],
  ["A (주력)", "GLM-4.6", "페르소나·번역·종합·윤리 2차", "한국어·소셜미디어·소설/카피 감정표현 공식 최적화, 경량·고효율"],
  ["B (플래그십·선택)", "GLM-5.1 (754B)", "심층 종합·복잡 추론(배치)", "SWE-Bench Pro 1위·MIT, GPU 확보 시 추가"],
  ["임베딩", "BGE-M3 / ko-sroberta", "매칭·지식공간", "한국어 멀티링궐, 자체호스팅"],
], [1500, 1900, 2400, 3226]));
ch.push(para("자체 서버 구동의 이점:"));
ch.push(table([
  ["항목", "내용"],
  ["비용 구조", "API 종량 과금 없음. 사용자 증가에도 서버 고정비"],
  ["데이터 보안", "대화가 외부로 전송되지 않아 개인정보 보호에 유리"],
  ["라이선스", "MIT — 상업적 이용·수정·배포·파인튜닝 무제한"],
  ["성능", "GLM-5.1 SWE-Bench Pro 58.4점(오픈소스 1위급), GLM-4.6 한국어·창작 최적화"],
  ["확장성", "vLLM 기반 멀티 GPU 스케일아웃, 다중 동시 처리"],
], [2400, 6626]));
ch.push(para("차별화 — 프라이버시 우선 매칭: 매칭 신호는 ‘사람에 대한 추론’이 아니라 ‘글·주제의 의미 임베딩(콘텐츠)’이다. 인지 파이프라인은 현재 메시지 텍스트만 읽는 규칙 기반으로, 누적 프로파일·민감속성 추론이 없다. 이는 개인정보보호와 편향 방지를 데이터 모델 수준에서 보장한다.", { bold: true, color: ACCENT }));

// 6
ch.push(new Paragraph({ children: [new PageBreak()] }));
ch.push(h1("6. 필요 인프라 사양"));
ch.push(h2("6-1. GPU 서버 (AI 추론용) — 모델 티어별"));
ch.push(table([
  ["시나리오", "GPU 요구", "스토리지/메모리"],
  ["GLM-4.6 주력 가동", "FP8 다중 GPU(중규모)", "NVMe SSD, 서버 메모리 충분"],
  ["GLM-4.5-Air 경량", "약 4×H100", "더 현실적 구성"],
  ["GLM-5.1 포함(플래그십)", "H100/H200(80GB) 8장급, FP8 640GB+", "모델 가중치 약 1.5TB"],
], [2900, 3100, 3026]));
ch.push(para("추론 프레임워크: vLLM (OpenAI 호환 API 자동 제공, FP8·prefix caching·speculative decoding으로 동시 처리량 최적화).", { size: 18, color: "777777" }));
ch.push(h2("6-2. 백엔드 서버 (앱 운영용)"));
ch.push(table([
  ["항목", "요구 사양"],
  ["서버 유형", "일반 VM 3대 (vCPU 12코어, RAM 24GB, SSD 150GB)"],
  ["용도", "FastAPI 백엔드, PostgreSQL+pgvector, Redis"],
], [2600, 6426]));

// 7
ch.push(h1("7. 인프라 지원 신청 계획"));
ch.push(h2("7-1. NIPA 첨단 GPU 활용 지원 (GPU 서버)"));
ch.push(table([
  ["항목", "내용"],
  ["주관/신청처", "과기정통부·NIPA / aiinfrahub.kr (국가 AI컴퓨팅자원 지원포털)"],
  ["지원 내용", "H200·B200 GPU 서버 직접 지원 (국내 중소기업 대상)"],
  ["활용 목적", "GLM 모델 구동 및 AI 대화·매개·매칭 서비스 운영"],
], [2600, 6426]));
ch.push(h2("7-2. 위치정보사업자 클라우드 지원 (백엔드 서버)"));
ch.push(table([
  ["항목", "내용"],
  ["주관/문의", "KISA / 02-6406-6100 · support@cloudlbs.kr"],
  ["신청기간", "2025.12.29 ~ 2026.09.30 (접수 중)"],
  ["지원 내용", "VM 3대 (vCPU 12, RAM 24GB, SSD 150GB)"],
  ["신청 대상", "창업 3년 미만 스타트업·예비창업자 (본 사업 해당)"],
], [2600, 6426]));
ch.push(para("전략: 신청서는 GLM-5.1을 플래그십으로 제시해 GPU 요구를 정당화하되, 실서비스 1차는 GLM-4.6로 가동해 선정 전에도 베타가 동작하게 한다.", { size: 18, color: "777777" }));

// 8
ch.push(h1("8. 자체 운영 vs 외부 API 비용 비교"));
ch.push(table([
  ["항목", "외부 API 방식", "자체 서버 방식(본 사업)"],
  ["토큰 과금", "사용량 비례 과금", "없음(서버 고정비만)"],
  ["사용자 1만명 기준", "월 수천만 원 예상", "서버비 고정"],
  ["데이터 보안", "외부 서버로 전송", "내부 서버에만 존재"],
  ["서비스 중단 리스크", "API 정책 변경 시 영향", "없음"],
  ["커스터마이징", "제한적", "파인튜닝 등 자유"],
], [2600, 3200, 3226]));

// 9 — 로드맵 (현재 위치 + 앞으로)
ch.push(h1("9. 사업 로드맵 (현재 위치 및 향후 계획)"));
ch.push(para("플랫폼 핵심(백엔드·프론트·테스트)은 완료 단계이며, 현재는 AI 실연동 착수 시점이다."));
ch.push(table([
  ["단계", "기간", "내용", "상태"],
  ["0단계", "~2026.5", "백엔드 5-AI·프론트 9화면·테스트 319·AI 통합 설계 (완료)", STAT.done],
  ["1단계", "2026.6~7", "지원사업 신청, 인프라 세팅, vLLM 서빙 + GLM-4.6 배포 + 임베딩/매칭 실연동", STAT.prog],
  ["2단계", "2026.7~8", "단일 경로 E2E(가입→생성→다국어 게시→매칭), DB 통합 검증, 대화 실시간 연동", STAT.plan],
  ["3단계", "2026.8~9", "5-AI 완전체 + 성능 최적화(FP8·prefix cache·speculative), 베타 출시", STAT.plan],
  ["4단계", "2026.10~", "정식 출시, (선정 시)GLM-5.1 심층 티어, 매칭 고도화·수익화", STAT.plan],
], [1100, 1500, 5126, 1300]));
ch.push(h2("9-1. 출시 전 필수 과제 (병행)"));
ch.push(bullet("위치기반서비스사업 신고(법적 필수), 개인정보처리방침·이용약관 정비"));
ch.push(bullet("관측성(에러 추적·지표 대시보드) 배선, 전송계층 TLS(+PQC 하이브리드) 적용"));
ch.push(bullet("DB 환경 통합 테스트 62개 실행으로 데이터 계층 전수 검증"));

// 10 — 요약
ch.push(h1("10. 요약"));
ch.push(para("buddle는 오픈소스 LLM(GLM, MIT)을 자체 서버에서 구동해 외부 API 비용 없이 지속 가능한 AI 소셜 서비스를 운영한다. 백엔드 5-AI 아키텍처·다국어 매개·pgvector 매칭·319개 자동화 테스트·9개 화면 프론트엔드가 이미 구현·검증되어 있으며, 본 단계의 과제는 AI 모델 실연동과 인프라 확보다. NIPA GPU와 KISA 위치기반 클라우드 지원을 동시 활용하면 초기 인프라 비용을 최소화하며 베타·정식 출시로 나아갈 수 있다."));
ch.push(table([
  ["신청 지원사업", "확보 인프라"],
  ["NIPA 첨단 GPU 지원 (aiinfrahub.kr)", "H200/B200 GPU → GLM 모델 구동"],
  ["KISA 위치기반 클라우드 지원", "VM 3대 → 백엔드/DB 서버"],
  ["합산 효과", "지원기간 동안 인프라 비용 최소화 + 자체 구동으로 토큰 과금 0"],
], [3600, 5426]));

const doc = new Document({
  styles: {
    default: { document: { run: { font: FONT, size: 20, color: INK } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: FONT, color: ACCENT },
        paragraph: { spacing: { before: 260, after: 150 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 23, bold: true, font: FONT, color: INK },
        paragraph: { spacing: { before: 200, after: 120 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [{ reference: "b", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 560, hanging: 280 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    children: ch,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync("/home/claude/buddle/AI_위치기반_매칭서비스_사업계획서_v2.docx", buf);
  console.log("docx written");
});
