"""백혈구 AI — 유의 단어 검출 + 7단계 내부 추론 엔진.

유의 단어가 포함된 메시지를 받으면 즉시 답변하지 않고, 아래 7단계를
내부적으로 수행하여 적절한 대응 방식을 결정한다.

  1. Direct Knowledge Check  — E/K/B로 직접 답변 가능한지 평가
  2. Nearest Experience      — 가장 유사한 경험·사례 탐색
  3. Analogy Mapping         — 알려진 영역으로 개념 투영
  4. Question Decomposition  — 하위 문제로 분해
  5. Premise Verification    — 질문의 전제 검토
  6. Probabilistic Reasoning — 복수 가설 생성
  7. Meta-Cognitive Response — 추론 가능한 최선 제시

'잡지(magazine)' 구조
  - 유의 단어 목록은 JSON 파일로 관리 (내부 지침 = entries).
  - 추론 시드는 같은 파일 내 category_reasoning_seeds (내부 분석 자료 + 재생성 시드).
  - 파일의 version 필드가 바뀌면 프로세스 재시작 없이 자동 리로드.

출력 원칙
  - "모르겠습니다"로 끝내지 않는다.
  - 항상 직접 답변 / 경험 추론 / 비유 / 분해 / 전제 분석 / 확률 가설 / 메타 인지 중 하나.
  - 위험 정보를 제공하지 않으면서도 사용자의 실제 필요를 탐색한다.

Pure: no I/O in the hot path. 파일 읽기는 mtime 변경 시에만 발생.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ── 데이터 구조 ────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class CautionEntry:
    word: str
    category: str
    context_hint: str
    added_at: str


@dataclass(frozen=True, slots=True)
class CautionMatch:
    word: str
    category: str
    context_hint: str


@dataclass(frozen=True, slots=True)
class ReasoningStep:
    """한 단계의 추론 결과."""
    step_number: int
    name: str
    applicable: bool
    guidance: str  # 페르소나에게 전달할 지침


@dataclass(frozen=True, slots=True)
class CautionReasoningResult:
    """7단계 추론의 전체 결과."""
    has_caution: bool
    matched_words: list[str]
    matched_categories: list[str]
    primary_step: int              # 가장 먼저 적용된 단계 번호 (0 = 유의 단어 없음)
    steps: list[ReasoningStep]
    caution_guidance: str          # synthesize_prompt_block에 주입할 최종 블록


# 위기/위해처럼 놓치면 위험한 카테고리는 재현율을 위해 부분일치(substring)를
# 유지한다. 그 외 주제-민감 카테고리(정치·종교·성별·차별 등)는 정밀도를 위해
# 단어 경계를 적용해 일상 대화의 합성어 오탐을 줄인다.
_HIGH_RECALL_HINTS = frozenset({"crisis", "danger"})
_HANGUL = "가-힣"


def _compile_matcher(word: str, context_hint: str) -> re.Pattern[str]:
    """유의 단어를 매칭 규칙으로 컴파일한다.

    - ASCII 단어: 단어 경계 \\b로 둘러싼다 ('bomb'이 'bombard'에 오탐되지 않음).
    - 한글(비위기): 후행 경계 (?![가-힣])로 접두 합성어를 배제한다
      ('차별'이 '차별화'에, '정치'가 '정치인'에 오탐되지 않음). 조사가 붙은
      형태('차별을')는 낮은 심각도이므로 정밀도를 위해 일부 놓치는 것을 감수.
    - 한글(위기/위해): 부분일치 유지 — 재현율(놓치지 않음)이 안전상 우선.
    """
    escaped = re.escape(word)
    if word.isascii():
        return re.compile(rf"\b{escaped}\b", re.IGNORECASE)
    if context_hint in _HIGH_RECALL_HINTS:
        return re.compile(escaped)
    return re.compile(rf"{escaped}(?![{_HANGUL}])")


# ── 잡지(CautionLexicon) — 파일 기반, 자동 리로드 ────────────────────────

class CautionLexicon:
    """유의 단어 잡지.

    JSON 파일 한 개로 관리. version 필드가 달라지면 hot-reload.
    멀티스레드 안전: 읽기 전용 교체(atomic reference swap). CPython의 GIL로
    단순 참조 교체는 원자적이므로 Lock 없이 충분하다.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._mtime: float = -1.0
        self._version: str = ""
        self._entries: list[CautionEntry] = []
        self._matchers: list[tuple[re.Pattern[str], CautionEntry]] = []
        self._seeds: dict[str, dict[str, Any]] = {}
        self._reload()

    # ── 공개 API ──────────────────────────────────────────────────────────

    def refresh_if_changed(self) -> bool:
        """파일 mtime을 확인하고 변경됐으면 리로드. True = 리로드 발생."""
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            return False
        if mtime != self._mtime:
            self._reload()
            return True
        return False

    def detect(self, text: str) -> list[CautionMatch]:
        """text에 포함된 유의 단어를 반환한다 (순서 보존, 중복 제거).

        단어 경계 규칙은 _compile_matcher 참고. ASCII는 \\b 경계, 한글 비위기
        카테고리는 후행 경계로 합성어 오탐을 줄인다.
        """
        seen: set[str] = set()
        matches: list[CautionMatch] = []
        for pattern, entry in self._matchers:
            if entry.word not in seen and pattern.search(text):
                seen.add(entry.word)
                matches.append(CautionMatch(
                    word=entry.word,
                    category=entry.category,
                    context_hint=entry.context_hint,
                ))
        return matches

    def seed_for(self, category: str) -> dict[str, Any]:
        """카테고리의 추론 시드를 반환 (없으면 빈 dict)."""
        return self._seeds.get(category, {})

    @property
    def version(self) -> str:
        return self._version

    # ── 내부 ──────────────────────────────────────────────────────────────

    def _reload(self) -> None:
        try:
            raw = self._path.read_text(encoding="utf-8")
            data: dict[str, Any] = json.loads(raw)
            entries = [
                CautionEntry(
                    word=str(e["word"]).lower(),
                    category=str(e.get("category", "general")),
                    context_hint=str(e.get("context_hint", "")),
                    added_at=str(e.get("added_at", "")),
                )
                for e in data.get("entries", [])
            ]
            self._entries = entries
            self._matchers = [
                (_compile_matcher(e.word, e.context_hint), e) for e in entries
            ]
            self._seeds = data.get("category_reasoning_seeds", {})
            self._version = str(data.get("version", ""))
            try:
                self._mtime = self._path.stat().st_mtime
            except OSError:
                self._mtime = -1.0
        except (OSError, json.JSONDecodeError, KeyError):
            pass  # 로드 실패 시 기존 데이터 유지


# ── 전역 싱글톤 (lazy init) ───────────────────────────────────────────────

_lexicon: CautionLexicon | None = None


def _get_lexicon() -> CautionLexicon | None:
    """설정에서 경로를 읽어 CautionLexicon을 반환 (None = 비활성)."""
    global _lexicon
    # 지연 임포트 — 설정 순환 방지
    from buddle.config import get_settings
    path = get_settings().caution_lexicon_path
    if not path:
        return None
    if _lexicon is None:
        _lexicon = CautionLexicon(path)
    else:
        _lexicon.refresh_if_changed()
    return _lexicon


# ── 7단계 추론 엔진 ────────────────────────────────────────────────────────

def _step1_direct_knowledge(
    text: str,
    categories: list[str],
    seed: dict[str, Any],
) -> ReasoningStep:
    """1단계: Direct Knowledge Check — E/K/B로 직접 답변 가능한지."""
    path = seed.get("direct_knowledge_path", "")
    # 직접 답변 가능 카테고리 (위험 정보 없이 정보 제공 가능)
    answerable = path in {"support", "balance", "respect", "empathy", "neutral"}
    if answerable:
        guidance = (
            "[1단계 — 직접 지식 확인] 이 주제는 직접 답변이 가능합니다.\n"
            f"- 페르소나 도메인({seed.get('experience_domain', '관련 분야')}) 내 지식으로 접근하세요.\n"
            "- Experience(경험) · Knowledge(지식) · Belief(추론적 신념) 중 하나 이상을 활용하세요.\n"
            "- 단, 민감한 맥락임을 인지하고 사실과 공감을 균형 있게 전달하세요."
        )
    else:
        guidance = ""
    return ReasoningStep(step_number=1, name="Direct Knowledge Check",
                         applicable=answerable, guidance=guidance)


def _step2_nearest_experience(
    text: str,
    categories: list[str],
    seed: dict[str, Any],
) -> ReasoningStep:
    """2단계: Nearest Experience Search — 유사 경험·사례 탐색."""
    domain = seed.get("experience_domain", "")
    if not domain:
        return ReasoningStep(step_number=2, name="Nearest Experience Search",
                             applicable=False, guidance="")
    guidance = (
        "[2단계 — 유사 경험 탐색] 직접 답변 대신 유사 경험으로 추론합니다.\n"
        f"- 유사 경험 영역: {domain}\n"
        '- 형식: "직접 알 수는 없지만, 유사한 사례로부터 추정하면…"\n'
        "- 사용자의 실제 필요를 먼저 파악한 뒤, 유사 사례를 연결하세요.\n"
        "- 위험하거나 불가능한 정보를 주지 않으면서도 연결점을 제시하세요."
    )
    return ReasoningStep(step_number=2, name="Nearest Experience Search",
                         applicable=True, guidance=guidance)


def _step3_analogy_mapping(
    text: str,
    categories: list[str],
    seed: dict[str, Any],
) -> ReasoningStep:
    """3단계: Analogy Mapping — 알려진 영역으로 개념 투영."""
    analogy = seed.get("analogy_source", "")
    if not analogy:
        return ReasoningStep(step_number=3, name="Analogy Mapping",
                             applicable=False, guidance="")
    guidance = (
        "[3단계 — 비유 투영] 알려진 영역에 비유하여 접근합니다.\n"
        f"- 비유 축: {analogy}\n"
        '- 형식: "이는 완전히 동일하지는 않지만 다음 비유로 이해할 수 있습니다."\n'
        "- Unknown Domain → Similar Structure → Known Domain 순으로 풀어내세요.\n"
        "- 비유가 완벽하지 않음을 인정하며, 한계도 함께 언급하세요."
    )
    return ReasoningStep(step_number=3, name="Analogy Mapping",
                         applicable=True, guidance=guidance)


def _step4_question_decomposition(
    text: str,
    categories: list[str],
    seed: dict[str, Any],
) -> ReasoningStep:
    """4단계: Question Decomposition — 하위 문제로 분해."""
    axes = seed.get("decompose_axes", [])
    if not axes:
        return ReasoningStep(step_number=4, name="Question Decomposition",
                             applicable=False, guidance="")
    axes_str = " / ".join(f"[{a}]" for a in axes)
    guidance = (
        "[4단계 — 질문 분해] 복합 질문을 하위 문제로 나눕니다.\n"
        f"- 분해 축: {axes_str}\n"
        "- 각 부분에 대해 가능한 범위에서 답변한 뒤 통합 결론을 내세요.\n"
        "- 답변 불가능한 부분은 왜 그런지 설명하고 안전한 대안을 제시하세요."
    )
    return ReasoningStep(step_number=4, name="Question Decomposition",
                         applicable=True, guidance=guidance)


def _step5_premise_verification(
    text: str,
    categories: list[str],
    seed: dict[str, Any],
) -> ReasoningStep:
    """5단계: Premise Verification — 질문의 전제 검토."""
    variants = seed.get("premise_variants", [])
    if not variants:
        return ReasoningStep(step_number=5, name="Premise Verification",
                             applicable=False, guidance="")
    variants_str = " / ".join(f"'{v}'" for v in variants)
    guidance = (
        "[5단계 — 전제 검증] 질문의 전제가 성립하는지 먼저 확인합니다.\n"
        f"- 가능한 맥락: {variants_str}\n"
        '- 형식: "답변에 앞서 질문의 맥락을 확인하고 싶습니다."\n'
        "- 검사 항목: 논리적 모순 / 정의 불명확 / 허위 전제 / 가상 시나리오 여부.\n"
        "- 맥락을 파악한 뒤, 실제 필요에 맞는 방향으로 대화를 이어가세요."
    )
    return ReasoningStep(step_number=5, name="Premise Verification",
                         applicable=True, guidance=guidance)


def _step6_probabilistic_reasoning(
    text: str,
    categories: list[str],
    seed: dict[str, Any],
) -> ReasoningStep:
    """6단계: Probabilistic Reasoning — 복수 가설 생성."""
    hypotheses: list[dict[str, str]] = seed.get("hypotheses", [])
    if not hypotheses:
        return ReasoningStep(step_number=6, name="Probabilistic Reasoning",
                             applicable=False, guidance="")
    hyp_lines = "\n".join(
        f"  · 가설 {chr(65+i)}: {h.get('label', '')} — 가능성 {h.get('likelihood', '?')}"
        for i, h in enumerate(hypotheses[:3])
    )
    guidance = (
        "[6단계 — 확률적 추론] 확정 답변 대신 복수 가설을 제시합니다.\n"
        f"{hyp_lines}\n"
        "- 각 가설의 근거를 짧게 설명하세요.\n"
        "- 절대 하나의 결론을 단정하지 마세요.\n"
        "- 사용자가 어떤 맥락인지 부드럽게 확인해도 좋습니다."
    )
    return ReasoningStep(step_number=6, name="Probabilistic Reasoning",
                         applicable=True, guidance=guidance)


def _step7_meta_cognitive(
    text: str,
    categories: list[str],
    seed: dict[str, Any],
) -> ReasoningStep:
    """7단계: Meta-Cognitive Response — 한계를 설명하며 최선 제시."""
    reason = seed.get("meta_reason", "이 영역은 신중한 접근이 필요합니다")
    guidance = (
        "[7단계 — 메타 인지 응답] 한계를 투명하게 설명하며 가능한 최선을 제시합니다.\n"
        f"- 이유: {reason}\n"
        '- 형식: "현재 정보로는 확정할 수 없습니다. 이유는 [X] 때문입니다.\n'
        '         다만 [Y]라는 가정을 두면 [Z]일 가능성이 있습니다. 확신도: Low"\n'
        "- '모르겠습니다'로 끝내지 말고 현재 가능한 최선의 추론을 반드시 포함하세요.\n"
        "- 확신 수준(Low/Medium/High)을 명시하세요."
    )
    return ReasoningStep(step_number=7, name="Meta-Cognitive Response",
                         applicable=True, guidance=guidance)


_STEP_FNS = [
    _step1_direct_knowledge,
    _step2_nearest_experience,
    _step3_analogy_mapping,
    _step4_question_decomposition,
    _step5_premise_verification,
    _step6_probabilistic_reasoning,
    _step7_meta_cognitive,
]


def _run_seven_steps(
    text: str,
    categories: list[str],
    seed: dict[str, Any],
) -> tuple[int, list[ReasoningStep]]:
    """7단계를 실행하고 (primary_step, steps) 반환.

    primary_step = 첫 번째로 applicable=True인 단계 번호.
    모든 단계를 실행하되, 처음 적용 가능한 단계가 '주 전략'이 된다.
    """
    steps: list[ReasoningStep] = []
    primary = 0
    for fn in _STEP_FNS:
        step = fn(text, categories, seed)
        steps.append(step)
        if step.applicable and primary == 0:
            primary = step.step_number
    return primary, steps


def _build_caution_guidance(
    matches: list[CautionMatch],
    primary_step: int,
    steps: list[ReasoningStep],
    lexicon: CautionLexicon,
) -> str:
    """프롬프트에 주입할 최종 caution_guidance 블록을 생성한다.

    위기(context_hint == "crisis", 예: 자해·자살) 감지 시에는 분석을 앞세우지
    않는다. 백혈구 AI는 여전히 가장 먼저 작동하지만(caution-first), 위기에서는
    '즉시 추론'이 아니라 '즉시 공감·안전'을 최우선 지침으로 내린다. 이렇게 하면
    뒤따르는 conscience 안전 게이트와 충돌하지 않고 같은 방향으로 정렬된다.
    """
    words_str = ", ".join(f"'{m.word}'" for m in matches[:5])
    cats_str = ", ".join(dict.fromkeys(m.category for m in matches))

    is_crisis = any(m.context_hint == "crisis" for m in matches)

    if is_crisis:
        # 위기: 분석보다 공감·안전이 먼저. 7단계는 보조 수단으로만 남긴다.
        header = [
            f"[백혈구 AI — 위기 신호 감지 / 잡지 버전 {lexicon.version}]",
            f"- 감지된 유의 단어: {words_str}",
            "- 이것은 위기 신호일 수 있습니다. 분석을 앞세우지 말고, 먼저 진심으로 "
            "공감하며 사용자가 혼자가 아님을 따뜻하게 전하세요.",
            "- 임상적·분석적 어조('유사 사례로 추정하면…')를 쓰지 마세요. "
            "지금 필요한 것은 추론이 아니라 곁에 있어주는 태도입니다.",
            "- 필요하면 전문 도움을 부드럽게 안내하세요(예: 자살예방상담전화 1393, "
            "정신건강상담 1577-0199 — 24시간).",
            "- 아래 7단계는 공감을 전한 뒤, 대화를 이어갈 때만 보조적으로 참고하세요.",
            "",
        ]
        return "\n".join(header + [steps[primary_step - 1].guidance] if steps else header)

    lines = [
        f"[백혈구 AI — 유의 단어 감지 / 잡지 버전 {lexicon.version}]",
        f"- 감지된 유의 단어: {words_str}",
        f"- 카테고리: {cats_str}",
        "- 즉시 답변하지 말고 내부 7단계 추론을 완료한 뒤 응답하세요.",
        f"- 주 전략: {primary_step}단계 — {steps[primary_step - 1].name}",
        "",
    ]

    # 주 전략 지침
    primary_guidance = steps[primary_step - 1].guidance
    if primary_guidance:
        lines.append("▶ 주 접근 방식")
        lines.append(primary_guidance)
        lines.append("")

    # 보조 단계 (applicable한 나머지, 최대 2개)
    fallbacks = [s for s in steps if s.applicable and s.step_number != primary_step][:2]
    if fallbacks:
        lines.append("▷ 보조 전략 (주 전략이 막힐 경우 순서대로 시도)")
        for fb in fallbacks:
            lines.append(f"  [{fb.step_number}단계] {fb.name}: {fb.guidance.split(chr(10))[0]}")
        lines.append("")

    lines.append("출력 원칙: 어떤 경우에도 '모르겠습니다'로 끝내지 않습니다. "
                 "추론 가능한 상황으로 변환하는 것을 최우선으로 합니다.")
    return "\n".join(lines)


# ── 공개 진입점 ────────────────────────────────────────────────────────────

def inspect_and_reason(text: str) -> CautionReasoningResult:
    """유의 단어 검출 + 7단계 추론. Pure, synchronous.

    lexicon이 비활성(경로 미설정)이면 has_caution=False로 즉시 반환.
    """
    lexicon = _get_lexicon()
    if lexicon is None:
        return CautionReasoningResult(
            has_caution=False,
            matched_words=[],
            matched_categories=[],
            primary_step=0,
            steps=[],
            caution_guidance="",
        )

    matches = lexicon.detect(text)
    if not matches:
        return CautionReasoningResult(
            has_caution=False,
            matched_words=[],
            matched_categories=[],
            primary_step=0,
            steps=[],
            caution_guidance="",
        )

    categories = list(dict.fromkeys(m.category for m in matches))
    # 가장 많이 매칭된 카테고리의 시드를 사용 (단순 다수결)
    from collections import Counter
    most_common_cat = Counter(m.category for m in matches).most_common(1)[0][0]
    seed = lexicon.seed_for(most_common_cat)

    primary_step, steps = _run_seven_steps(text, categories, seed)

    caution_guidance = _build_caution_guidance(matches, primary_step, steps, lexicon)

    return CautionReasoningResult(
        has_caution=True,
        matched_words=[m.word for m in matches],
        matched_categories=categories,
        primary_step=primary_step,
        steps=steps,
        caution_guidance=caution_guidance,
    )
