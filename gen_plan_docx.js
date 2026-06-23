const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, LevelFormat, HeadingLevel, BorderStyle, WidthType, ShadingType, PageBreak,
} = require("docx");

const FONT = "Malgun Gothic";
const INK = "2F4F4F";
const ACCENT = "5B6FB0";
const CW = 9026; // A4 content width (1" margins)

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 80, bottom: 80, left: 120, right: 120 };

function h1(t) { return new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] }); }
function h2(t) { return new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] }); }
function p(t, opts = {}) {
  return new Paragraph({ spacing: { after: 120, line: 300 }, children: [new TextRun({ text: t, ...opts })] });
}
function bullet(t) {
  return new Paragraph({ numbering: { reference: "b", level: 0 }, spacing: { after: 60, line: 290 },
    children: [new TextRun(t)] });
}
function cell(text, { w, head = false, bold = false } = {}) {
  return new TableCell({
    borders, width: { size: w, type: WidthType.DXA }, margins: cellMargins,
    shading: { fill: head ? "E9ECF6" : "FFFFFF", type: ShadingType.CLEAR },
    children: [new Paragraph({ children: [new TextRun({ text: text, bold: head || bold, color: head ? ACCENT : INK })] })],
  });
}
function table(rows, widths) {
  return new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: widths,
    rows: rows.map((r, i) => new TableRow({
      children: r.map((c, j) => cell(c, { w: widths[j], head: i === 0 })),
    })),
  });
}

const children = [];

// ── Title ──
children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 },
  children: [new TextRun({ text: "buddle", font: "Georgia", bold: true, size: 56, color: ACCENT })] }));
children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 },
  children: [new TextRun({ text: "AI 매개 다국어·위치기반 소셜 플랫폼", bold: true, size: 28, color: INK })] }));
children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 },
  children: [new TextRun({ text: "사업계획 및 인프라 지원 신청서", size: 24, color: INK })] }));
children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 },
  children: [new TextRun({ text: "메트리아(Metria) · 2026년 6월 · 창업 2개월차", size: 20, color: "888888" })] }));

// ── 1 ──
children.push(h1("1. 사업 개요"));
children.push(p("buddle는 AI가 사람과 사람 사이의 의사소통을 매개하여, 언어 장벽을 넘어 생각이 닿게 하는 위치기반 소셜 플랫폼이다. 사용자는 떠오르는 생각을 자유롭게 적기만 하면, AI 페르소나가 이를 다듬어 다국어로 게시하고, 알고리즘이 어울리는 상대를 찾아 그 사람의 언어로 전달한다."));
children.push(p("핵심 차별점은 'AI가 사람을 분석·판정하지 않는다'는 데 있다. 매칭은 사용자의 성향을 프로파일링하는 것이 아니라, 사용자가 남긴 '콘텐츠(글·주제)'의 의미 임베딩 유사도로 이루어진다. 이는 개인정보 보호와 편향 방지를 데이터 모델 수준에서 보장하는 구조적 강점이다."));
children.push(table([
  ["항목", "내용"],
  ["서비스명", "buddle — AI 매개 다국어·위치기반 소셜 플랫폼"],
  ["운영사", "메트리아(Metria) · 사업자등록 585-03-03590"],
  ["창업일", "2026년 4월 (창업 2개월차)"],
  ["대상", "언어·지역을 넘어 생각이 통하는 연결을 원하는 일반 소비자"],
  ["핵심 기술", "자체 서버 구동 오픈소스 LLM(GLM, MIT) + 벡터 임베딩 매칭 + 위치 근접"],
], [2600, 6426]));

// ── 2 ──
children.push(h2("2. 핵심 기능"));
children.push(table([
  ["기능", "설명", "AI 활용"],
  ["① 대화", "AI 페르소나와 자연어로 대화하며 생각을 정리·표현", "GLM-4.6이 따뜻한 한국어 대화·다국어 글 생성"],
  ["② 매개·번역", "다듬어진 생각을 공개/비공개로 게시하고 상대 언어로 전달", "GLM-4.6 번역(한↔영) + 매개자 AI 라우팅"],
  ["③ 매칭", "유사한 관심을 가진 가까운 사용자를 연결", "콘텐츠 임베딩 유사도 + 위치 근접(프로파일링 없음)"],
], [1700, 3900, 3426]));
children.push(p("부가로, 권한이 분리된 5개 AI가 협력한다: 페르소나(사용자 대면), 매개자(게시·전달), 백혈구(콘텐츠 윤리·중요도), 기술자(무결성 서명), 중앙관리자(시스템 총괄). 사람을 점수화하는 AI는 없다.", { italics: true }));

// ── 3 ──
children.push(h2("3. 시스템 아키텍처"));
children.push(bullet("사용자 앱 → API 게이트웨이(FastAPI) → 자체 GLM 추론 서버(vLLM, OpenAI 호환)"));
children.push(bullet("대화·글·지식 → PostgreSQL 16 저장 / 콘텐츠 임베딩 → pgvector(동일 DB 내 벡터 검색)"));
children.push(bullet("매칭 요청 → pgvector 코사인 유사도 + 위치 근접(haversine 동심원) → 결과 반환"));
children.push(bullet("GLM은 외부 API 없이 사설망 내부에서 완전 구동 — 사용자 데이터 외부 유출 없음"));
children.push(p("주: 벡터 검색은 별도 시스템(Qdrant) 없이 PostgreSQL의 pgvector 확장으로 처리하여 운영 단순성과 데이터 일관성을 확보한다(대규모 확장 시 전용 벡터 DB·PostGIS 도입 검토).", { size: 18, color: "777777" }));

// ── 4 ──
children.push(h2("4. 기술 스택"));
children.push(table([
  ["역할", "기술", "선택 이유"],
  ["대화·번역·종합 LLM", "GLM-4.6 (MIT)", "한국어·소셜·창작 감정표현 공식 최적화, 자체 구동"],
  ["심층 추론(선택)", "GLM-5.1 (754B, MIT)", "프런티어급 추론·장기 컨텍스트, 고난도 종합 배치"],
  ["추론 서버", "vLLM", "OpenAI 호환, FP8·연속배칭·speculative로 고처리량"],
  ["백엔드", "FastAPI (Python, async)", "비동기 고성능, 빠른 개발"],
  ["DB / 벡터", "PostgreSQL 16 + pgvector", "관계형+벡터 단일 DB, 운영 단순"],
  ["임베딩", "ko-sroberta(768) → BGE-M3(1024)", "한국어 자체호스팅, 단계적 업그레이드"],
  ["캐시·세션", "Redis", "레이트리밋·세션·임베딩 캐시"],
  ["위치", "haversine 근접(→ PostGIS 확장)", "초기 경량, 확장 시 공간 인덱스"],
], [2300, 2700, 4026]));

// ── 5 ──
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(h1("5. 모델 선택 근거 (자체 서버 · 외부 API 미사용)"));
children.push(p("작업 성격에 따라 모델을 티어링한다. 코딩 벤치마크 1위 모델이 곧 '따뜻한 한국어 소셜 글쓰기' 1위는 아니라는 판단에 따라, 페르소나의 본질에 맞는 모델을 1차 워크호스로 둔다."));
children.push(table([
  ["티어", "모델", "용도", "근거"],
  ["A(주력)", "GLM-4.6", "페르소나·번역·종합·윤리2차", "한국어·소셜미디어·소설/카피 감정표현 공식 최적화, 가벼움"],
  ["B(선택)", "GLM-5.1 754B", "심층 종합·복잡 추론(배치)", "SWE-Bench Pro 1위·MIT, GPU 확보 시 추가"],
  ["임베딩", "BGE-M3 / ko-sroberta", "매칭·지식공간", "한국어 멀티링궐, 자체호스팅"],
], [1300, 1900, 2600, 3226]));
children.push(p("자체 서버 구동의 이점:"));
children.push(table([
  ["항목", "내용"],
  ["비용 구조", "API 종량 과금 없음. 사용자 증가에도 서버 고정비"],
  ["데이터 보안", "대화가 외부로 전송되지 않아 개인정보 보호에 유리"],
  ["라이선스", "MIT — 상업적 이용·수정·배포·파인튜닝 무제한"],
  ["확장성", "vLLM 기반 멀티 GPU 스케일아웃, 다중 동시 처리"],
  ["주권", "API 정책 변경·중단 리스크 없음, 로드맵 자체 통제"],
], [2600, 6426]));

// ── 6 ──
children.push(h2("6. 차별화 — 프라이버시 우선 매칭"));
children.push(p("일반적인 'AI 성향 분석' 매칭과 달리, buddle는 사용자를 프로파일링하지 않는다. AI는 사람이 아니라 '콘텐츠'를 다룬다."));
children.push(bullet("매칭 신호 = 글·주제의 의미 임베딩(콘텐츠), 사람에 대한 추론 아님"));
children.push(bullet("인지 파이프라인은 현재 메시지 텍스트만 읽는 규칙 기반(누적 프로파일·민감속성 추론 없음)"));
children.push(bullet("결과: 윤리적 안전(편향↓) + 프라이버시 강점 + 개인정보보호법 부담↓"));
children.push(p("\"AI가 당신을 판정하지 않고, 당신의 생각을 언어 너머로 전달한다\" — 이것이 buddle의 약속이자 기술적 구조다.", { bold: true, color: ACCENT }));

// ── 7 ──
children.push(h2("7. 필요 인프라 (모델 티어별)"));
children.push(table([
  ["시나리오", "GPU(추론)", "적합 지원"],
  ["GLM-4.6 단일(주력)", "FP8 다중 GPU(중규모)", "NIPA GPU + KISA 클라우드"],
  ["GLM-4.5-Air 경량", "약 4×H100", "더 현실적·빠른 선정"],
  ["GLM-5.1 포함(플래그십)", "약 8×H200 (FP8)", "NIPA H200/B200 프로그램"],
], [2900, 3100, 3026]));
children.push(p("백엔드(FastAPI·PostgreSQL·Redis)는 일반 VM 3대(vCPU 12, RAM 24GB, SSD 150GB)로 충분하며 KISA 위치정보 클라우드 지원으로 충당한다."));

// ── 8 ──
children.push(h2("8. 인프라 지원 신청 계획"));
children.push(table([
  ["지원사업", "주관/신청처", "확보 인프라"],
  ["NIPA 첨단 GPU 활용 지원", "과기정통부·NIPA / aiinfrahub.kr", "H200·B200 GPU → GLM 구동"],
  ["위치정보사업자 클라우드 지원", "KISA / support@cloudlbs.kr (2025.12.29~2026.09.30 접수)", "VM 3대 → 백엔드·DB"],
], [2700, 3500, 2826]));
children.push(p("전략: 신청서는 GLM-5.1을 플래그십으로 제시해 GPU 요구를 정당화하되, 실서비스 1차는 GLM-4.6로 가동해 선정 전에도 베타가 동작하게 한다.", { size: 18, color: "777777" }));

// ── 9 ──
children.push(h2("9. 자체 운영 vs 외부 API 비용 비교"));
children.push(table([
  ["항목", "외부 API", "자체 서버(본 사업)"],
  ["토큰 과금", "사용량 비례", "없음(서버 고정비)"],
  ["사용자 1만명", "월 수천만 원 예상", "서버비 고정"],
  ["데이터 보안", "외부 전송", "내부에만 존재"],
  ["중단 리스크", "정책 변경 영향", "없음"],
  ["커스터마이징", "제한적", "파인튜닝 자유"],
], [2600, 3200, 3226]));

// ── 10 ──
children.push(h2("10. 로드맵"));
children.push(table([
  ["단계", "기간", "내용"],
  ["1단계", "2026.6~7", "지원사업 신청, 인프라 세팅, GLM-4.6 배포 + 임베딩/매칭 실연동"],
  ["2단계", "2026.7~8", "단일 경로 E2E(가입→생성→다국어 게시→매칭), DB 통합 검증"],
  ["3단계", "2026.8~9", "5-AI 완전체 + 성능 최적화(FP8·prefix cache·speculative), 베타 출시"],
  ["4단계", "2026.10~", "정식 출시, (선정 시)GLM-5.1 심층 티어, 매칭 고도화·수익화"],
], [1300, 1700, 6026]));

// ── 11 ──
children.push(h2("11. 요약"));
children.push(p("buddle는 오픈소스 LLM(GLM, MIT)을 자체 서버에서 구동해 외부 API 비용 없이 지속 가능한 AI 소셜 서비스를 운영한다. 핵심 기술 자산은 이미 구현되어 있으며(백엔드 5-AI 아키텍처, 다국어 매개, pgvector 매칭, 319개 자동화 테스트 통과, 9개 화면 프론트엔드), 본 단계는 AI 모델 실연동과 인프라 확보다. NIPA GPU와 KISA 클라우드 지원을 동시 활용하면 초기 인프라 비용을 최소화하며 론칭할 수 있다."));

const doc = new Document({
  styles: {
    default: { document: { run: { font: FONT, size: 20, color: INK } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: FONT, color: ACCENT },
        paragraph: { spacing: { before: 260, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: FONT, color: ACCENT },
        paragraph: { spacing: { before: 220, after: 140 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [ { reference: "b", levels: [ { level: 0, format: LevelFormat.BULLET, text: "•",
    alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 560, hanging: 280 } } } } ] } ] },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync("/home/claude/buddle/buddle_사업계획서_보강본.docx", buf);
  console.log("docx written");
});
