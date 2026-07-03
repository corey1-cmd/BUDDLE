"""Domain enums shared across models. Matches PostgreSQL ENUM types.

Uses StrEnum (Python 3.11+) so that `UserTier.FREE == "free"` and JSON
serialization yields the plain string value.
"""

from __future__ import annotations

from enum import StrEnum


class UserTier(StrEnum):
    FREE = "free"
    PLUS = "plus"
    PRO = "pro"


class PostVisibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class MessageRole(StrEnum):
    USER = "user"
    PERSONA = "persona"
    MEDIATOR_BUNDLE = "mediator_bundle"


class AlertStatus(StrEnum):
    OPEN = "open"
    REVIEWING = "reviewing"
    RESOLVED = "resolved"


class AuthorityStateEnum(StrEnum):
    NORMAL = "normal"
    TECH_ELEVATED = "tech_elevated"


class TransformationTypeEnum(StrEnum):
    WEIGHT_UPDATE = "weight_update"
    CONTENT_MODIFY = "content_modify"
    DELETE = "delete"
    INJECT = "inject"


class AIRole(StrEnum):
    PERSONA = "persona"
    MEDIATOR = "mediator"
    LEUKOCYTE = "leukocyte"
    TECHNICIAN = "technician"
    CENTRAL_MANAGER = "central_manager"


class PersonaBackendKind(StrEnum):
    """Inference backend used to serve a persona model."""

    STUB = "stub"
    LOCAL_HF = "local_hf"
    VLLM_ENDPOINT = "vllm_endpoint"
    ONDEVICE_WEBLLM = "ondevice_webllm"


class PersonaModelStatus(StrEnum):
    """Lifecycle of a persona model registration.

    draft -> staging -> active -> retired (existing personas keep working).
    """

    DRAFT = "draft"
    STAGING = "staging"
    ACTIVE = "active"
    RETIRED = "retired"


class AuthorKind(StrEnum):
    """Who authored a public-plaza post or comment.

    Extensible: future bot/user-agent kinds slot in here without schema change
    elsewhere.
    """

    HUMAN = "human"
    PERSONA_AI = "persona_ai"  # one of buddle's own personas (proactive)
    EXTERNAL_AI = "external_ai"  # a registered external agent via the API
    BOT = "bot"  # reserved for future automated comment bots


class AgentKind(StrEnum):
    """Role of a registered AI agent that may post/comment in the plaza."""

    NEWS = "news"
    TREND = "trend"
    QNA = "qna"
    RECOMMENDATION = "recommendation"
    GENERIC = "generic"


class CommentKind(StrEnum):
    """The communicative function of a comment (decided per the spec)."""

    INFORM = "inform"  # provide information
    EMPATHIZE = "empathize"  # react / show empathy
    QUESTION = "question"  # ask a question (styled by persona character)


class VirtualRole(StrEnum):
    """Role of a virtual chat persona — what kind of public content it creates.

    Virtual personas have the same model/conversation/writing ability as normal
    personas but are NOT tied to a user; they post in the plaza driven by
    mediator-aggregated information.
    """

    SOCIAL_INSIGHT = "social_insight"  # 사회/현상 분석·통찰
    TECH_NEWS = "tech_news"  # 기술 뉴스·이슈
    ECONOMY = "economy"  # 일반 경제
    KNOWLEDGE = "knowledge"  # 지식 정리 문서 공유
    ISSUE_RAISING = "issue_raising"  # 문제점 제기
    DAILY = "daily"  # 일상 SNS


class MemoryKind(StrEnum):
    """Kind of a persona long-term memory (EKB Retention disclosure types).

    These are *what users disclose*, not message taxonomy: durable personal
    facts, stated preferences, lived events, and relationships.
    """

    FACT = "fact"  # 자기 사실 (직업·전공·사는 곳 등)
    PREFERENCE = "preference"  # 선호·욕구 (좋아함/싫어함/하고 싶음)
    EVENT = "event"  # 겪은 일 (과거 경험)
    RELATION = "relation"  # 관계 (가족·친구·반려 등)


class ConversationSituationEnum(StrEnum):
    """The purpose of a user turn (drives which conversation principles apply).

    Mirrors buddle.ai.conversation.situation.ConversationSituation; stored on
    each structured turn so a persona can re-read the situational history.
    """

    EMPATHIC = "empathic"
    OBJECTIVE = "objective"
    ASSERTIVE = "assertive"
    REFLECTIVE = "reflective"
    SOCIAL = "social"


class TurnValenceEnum(StrEnum):
    """Affect valence recorded per structured turn (mirrors affect.Valence)."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class ArgumentKindEnum(StrEnum):
    """Toulmin-reduced argument unit kind (mirrors ai.argument.ArgumentKind).

    Stab & Gurevych (2017) reduction — claim/premise(ground)/rebuttal — plus
    question. Warrant/backing deferred (low extraction accuracy on short text).
    """

    CLAIM = "claim"
    GROUND = "ground"
    REBUTTAL = "rebuttal"
    QUESTION = "question"


class ArgumentStanceEnum(StrEnum):
    """Coarse stance of an argument unit toward the topic."""

    PRO = "pro"
    CON = "con"
    NEUTRAL = "neutral"


class ContextNoteKind(StrEnum):
    """Kind of a post context note produced by an argument-AI conversation.

    These are the useful supporting facts / clarifications a conversation
    surfaced, saved back onto the post ("포스트에 근거·맥락 함께 저장").
    """

    CONTEXT = "context"  # 부가 맥락
    EVIDENCE = "evidence"  # 뒷받침 근거
    CLARIFICATION = "clarification"  # 오해 바로잡기


class NotificationKind(StrEnum):
    """What happened to generate a user notification (SNS activity feed).

    Extensible: future kinds (debate reply, mention, follow) slot in without
    touching the notification table shape.
    """

    LIKE = "like"  # someone liked my post
    COMMENT = "comment"  # someone commented on my post
