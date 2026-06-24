"""News ingestion package — fetch, analyse, store open-web tech content.

Pipeline (runs as background scheduler job every hour):
  1. fetcher.py   — HTTP/RSS/HN API → list[RawArticle]
  2. mediator.py  — Gemini/vLLM → gist + EKB-tagged briefing per article
  3. news_service.py — dedup (Redis) + store briefings + KnowledgeAudit log
"""
