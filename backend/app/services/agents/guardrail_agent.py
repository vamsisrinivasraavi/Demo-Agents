"""
Agent 3: Guardrail + Validation Agent.

Final agent in the pipeline. Validates the accumulated response for:
1. Hallucination — does the response match the actual schema context?
2. SQL injection — does the generated SQL contain dangerous patterns?
3. PII exposure — does the response leak sensitive data patterns?
4. Output quality — is the response coherent and helpful?

Uses LLM-as-judge for semantic validation + regex patterns for SQL safety.
Always runs last. Can either APPROVE or REJECT the response.
"""

import re
from typing import Optional

import openai

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.workflow import AgentType, GuardrailAgentConfig
from app.services.agents.base import (
    AgentContext,
    AgentResult,
    AgentStatus,
    BaseAgent,
)

logger = get_logger(__name__)

# ──────────────────────────────────────────────
# SQL Safety Patterns
# ──────────────────────────────────────────────

DANGEROUS_SQL_PATTERNS = [
    re.compile(r"\bDROP\s+(TABLE|DATABASE|INDEX|VIEW)\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\s+\w+\s*(?!.*\bWHERE\b)", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bALTER\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bUPDATE\s+\w+\s+SET\s+.*(?!.*\bWHERE\b)", re.IGNORECASE),
    re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE),
    re.compile(r"\bEXEC(UTE)?\s*\(", re.IGNORECASE),
    re.compile(r"\bxp_cmdshell\b", re.IGNORECASE),
    re.compile(r"\bsp_executesql\b", re.IGNORECASE),
    re.compile(r";\s*(DROP|DELETE|TRUNCATE|ALTER|UPDATE|INSERT)", re.IGNORECASE),
    re.compile(r"--\s*$", re.MULTILINE),  # SQL comment injection
    re.compile(r"\bUNION\s+SELECT\b", re.IGNORECASE),  # UNION injection
]

PII_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN
    re.compile(r"\b\d{16}\b"),  # Credit card (basic)
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),  # Email
    re.compile(r"password\s*[:=]\s*\S+", re.IGNORECASE),  # Password leaks
    re.compile(r"api[_-]?key\s*[:=]\s*\S+", re.IGNORECASE),  # API key leaks
]


class GuardrailAgent(BaseAgent):
    """
    Validation and safety guardrail agent.

    Performs three layers of validation:
    1. Pattern-based SQL safety check (fast, deterministic)
    2. Pattern-based PII detection (fast, deterministic)
    3. LLM-as-judge hallucination check (slower, semantic)

    If any check fails, the response is sanitized or replaced
    with a safe fallback message.
    """

    agent_type = AgentType.GUARDRAIL

    async def should_run(self, context: AgentContext) -> bool:
        """Guardrail always runs if enabled — it's the safety net."""
        agent_configs = context.workflow_config.get("agents", [])
        for ac in agent_configs:
            if ac.get("type") == AgentType.GUARDRAIL:
                return ac.get("enabled", True)
        return True  # Default to running even if not explicitly configured

    async def _execute(self, context: AgentContext) -> AgentResult:
        """Run all validation checks on the accumulated response."""
        # Get config
        agent_configs = context.workflow_config.get("agents", [])
        guardrail_cfg = GuardrailAgentConfig()
        for ac in agent_configs:
            if ac.get("type") == AgentType.GUARDRAIL:
                guardrail_cfg = GuardrailAgentConfig(**ac.get("config", {}))
                break

        # Determine the response to validate
        response_to_validate = (
            context.web_search_response
            or context.retrieval_response
            or ""
        )
        sql_to_validate = context.retrieval_sql_query

        issues: list[str] = []
        sanitized_response = response_to_validate

        # ── Check 1: SQL Safety ──
        if guardrail_cfg.check_sql_injection and sql_to_validate:
            sql_issues = self._check_sql_safety(sql_to_validate)
            if sql_issues:
                issues.extend(sql_issues)
                logger.warning(
                    "guardrail.sql_issues",
                    issues=sql_issues,
                    sql=sql_to_validate[:200],
                )
                # Remove the dangerous SQL from the response
                sanitized_response = self._redact_sql(
                    sanitized_response, sql_to_validate
                )

        # ── Check 2: PII Detection ──
        if guardrail_cfg.check_pii_exposure:
            pii_issues = self._check_pii(response_to_validate)
            if pii_issues:
                issues.extend(pii_issues)
                sanitized_response = self._redact_pii(sanitized_response)
                logger.warning("guardrail.pii_detected", issues=pii_issues)

        # ── Check 3: Blocked Topics ──
        blocked = self._check_blocked_topics(
            response_to_validate, guardrail_cfg.blocked_topics
        )
        if blocked:
            issues.extend(blocked)

        # ── Check 4: LLM Hallucination Check ──
        if guardrail_cfg.check_hallucination and not issues:
            hallucination_issues = await self._check_hallucination(
                query=context.query,
                response=response_to_validate,
                tables=context.retrieval_tables,
                used_columns=context.retrieval_used_columns,
                output_columns=context.retrieval_output_columns,
                sql_result_preview=context.retrieval_sql_result_preview,
                retrieval_confidence=context.retrieval_confidence,
                web_search_sources=context.web_search_sources,
                web_search_response=context.web_search_response,
            )
            if hallucination_issues:
                issues.extend(hallucination_issues)

        # ── Final Decision ──
        if issues:
            context.validation_issues = issues
            context.is_validated = False

            # If critical issues (SQL injection), replace response entirely
            has_critical = any("SQL" in i or "injection" in i for i in issues)
            if has_critical:
                if context.web_search_response:
                    context.final_response = (
                        f"I found some information related to your question, but the generated query was flagged "
                        f"by safety checks. I have found this information from the web that might help you:\n\n"
                        f"Here's what I found:\n\n{context.web_search_response}\n\n"
                        "Please note that the information may not be directly relevant to your question, so I recommend reviewing it carefully."
                    )
                else:
                    context.final_response = (
                        "I found relevant information but the generated query was flagged "
                        "by safety checks. Please rephrase your question or contact an admin."
                    )
            else:
                # Non-critical: use sanitized version with disclaimer
                context.final_response = (
                    f"{sanitized_response}\n\n"
                    "_Note: This response was flagged for review. "
                    "Please verify the information independently._"
                )

            logger.info("guardrail.issues_found", count=len(issues), issues=issues)
        else:
            context.is_validated = True
            context.final_response = sanitized_response
            context.validation_issues = []

        return AgentResult(
            agent_type=self.agent_type,
            status=AgentStatus.SUCCESS,
            response=context.final_response,
            confidence=1.0 if not issues else 0.5,
            metadata={
                "issues": issues,
                "validated": context.is_validated,
                "checks_performed": [
                    "sql_safety" if guardrail_cfg.check_sql_injection else None,
                    "pii_detection" if guardrail_cfg.check_pii_exposure else None,
                    "hallucination" if guardrail_cfg.check_hallucination else None,
                    "blocked_topics",
                ],
            },
        )

    # ──────────────────────────────────────────────
    # Validation Methods
    # ──────────────────────────────────────────────

    @staticmethod
    def _check_sql_safety(sql: str) -> list[str]:
        """Check SQL for dangerous patterns."""
        issues = []
        for pattern in DANGEROUS_SQL_PATTERNS:
            if pattern.search(sql):
                issues.append(
                    f"SQL safety: Detected dangerous pattern '{pattern.pattern}'"
                )
        return issues

    @staticmethod
    def _check_pii(text: str) -> list[str]:
        """Check response for PII patterns."""
        issues = []
        for pattern in PII_PATTERNS:
            matches = pattern.findall(text)
            if matches:
                issues.append(
                    f"PII detected: Pattern '{pattern.pattern}' found {len(matches)} match(es)"
                )
        return issues

    @staticmethod
    def _check_blocked_topics(text: str, blocked: list[str]) -> list[str]:
        """Check if response mentions blocked topics."""
        issues = []
        lower_text = text.lower()
        for topic in blocked:
            if topic.lower() in lower_text:
                issues.append(f"Blocked topic detected: '{topic}'")
        return issues

    @staticmethod
    async def _check_hallucination(
        query: str,
        response: str,
        tables: list[str],
        used_columns: list[str],
        output_columns: list[str],
        sql_result_preview: Optional[str] = None,
        retrieval_confidence: float = 0.0,
        web_search_sources: Optional[list[str]] = None,
        web_search_response: Optional[str] = None,
    ) -> list[str]:
        """
        Use LLM-as-judge to check for hallucinated content.
        The LLM verifies whether the response is grounded in the
        table schemas that were actually retrieved.
        """
        if not response or len(response.strip()) < 30:
            return []

        settings = get_settings()
        client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

        prompt = (
            "You are a strict but practical data validation agent. Your job is to verify whether the response "
            "is grounded in reliable data sources, while allowing minor wording variations.\n\n"

            f"User question: {query}\n"
            f"Tables referenced: {', '.join(tables) if tables else 'None'}\n"
            f"Used columns: {', '.join(used_columns) if used_columns else 'None'}\n"
            f"Output columns: {', '.join(output_columns) if output_columns else 'None'}\n"
            f"SQL result preview: {sql_result_preview if sql_result_preview else 'None'}\n"
            f"Retrieval confidence: {retrieval_confidence}\n"
            f"Web search response: {web_search_response if web_search_response else 'None'}\n\n"

            f"Response to validate:\n{response[:1500]}\n\n"

            "DECISION LOGIC:\n"
            "1. If retrieval confidence >= 0.4 AND SQL result preview is present:\n"
            "   → Validate against SQL\n"
            "2. If retrieval confidence < 0.4 AND SQL result preview is missing:\n"
            "   → Validate against web response\n"
            "3. If no data available → FAIL\n\n"

            "ALLOWED VARIATIONS (DO NOT FLAG AS ISSUE):\n"
            "- Minor wording differences (e.g., 'Dev' vs 'Developer')\n"
            "- Abbreviations or expansions (e.g., 'Cloud Eng' vs 'Cloud Engineer')\n"
            "- Equivalent phrasing with same meaning\n"
            "- Case or formatting differences\n\n"

            "STRICT VALIDATION RULES:\n"
            "- Do NOT allow invented rows or entirely new values\n"
            "- Each row must map to a real row in the source data\n"
            "- Semantic meaning must match even if wording differs\n"
            "- If meaning changes → FAIL\n\n"

            "FAIL CONDITIONS:\n"
            "- Completely new roles/entities not present in source → FAIL\n"
            "- Mismatch in meaning (not just wording) → FAIL\n"
            "- Fabricated data → FAIL\n\n"

            "SPECIAL INSTRUCTION:\n"
            "If differences are ONLY minor wording variations, respond with APPROVED.\n"
            "Do NOT raise issues for abbreviation or naming differences.\n\n"

            "Respond with ONLY:\n"
            "- 'APPROVED'\n"
            "- OR 'ISSUE: <exact problem>'"
        )

        try:
            result = await client.chat.completions.create(
                model="gpt-4o-mini",  # Cheaper model for validation
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=150,
            )

            judgment = result.choices[0].message.content or ""

            if judgment.strip().upper().startswith("APPROVED"):
                return []
            else:
                return [f"Hallucination check: {judgment.strip()}"]

        except Exception as e:
            logger.warning("guardrail.hallucination_check_failed", error=str(e))
            return []  # Don't block on validation failure

    # ──────────────────────────────────────────────
    # Sanitization Helpers
    # ──────────────────────────────────────────────

    @staticmethod
    def _redact_sql(response: str, dangerous_sql: str) -> str:
        """Remove dangerous SQL from the response text."""
        return response.replace(dangerous_sql, "[SQL REDACTED FOR SAFETY]")

    @staticmethod
    def _redact_pii(text: str) -> str:
        """Replace PII patterns with redaction markers."""
        result = text
        for pattern in PII_PATTERNS:
            result = pattern.sub("[REDACTED]", result)
        return result