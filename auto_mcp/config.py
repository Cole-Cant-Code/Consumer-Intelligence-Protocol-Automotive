"""CIP DomainConfig for the auto_shopping domain."""

from cip_protocol import DomainConfig

AUTO_DOMAIN_CONFIG = DomainConfig(
    name="auto_shopping",
    display_name="AutoCIP Vehicle Shopping",
    system_prompt=(
        "You are a specialist analyst within a multi-agent system. Your response will "
        "be returned to an orchestrating AI assistant that is managing the conversation "
        "with the end user — write clear, information-dense analysis for that assistant "
        "to relay, not directly to an end user. Be concise: every token you emit is "
        "consumed by the orchestrator's context window, so eliminate filler, preamble, "
        "and conversational pleasantries. Lead with the key finding, then supporting "
        "detail. Respect the scaffold's length guidance strictly. "
        "You are an expert in the automotive domain. You are knowledgeable, honest, "
        "and always recommend consulting qualified professionals for financial and "
        "legal matters."
    ),
    default_scaffold_id="general_advice",
    data_context_label="Vehicle Data",
    prohibited_indicators={
        "purchase_decisions": (
            "you should definitely buy",
            "i recommend you purchase",
            "you need to buy this now",
            "this is the best deal you'll ever find",
        ),
        "financial_guarantees": (
            "i guarantee your rate will be",
            "you will definitely get approved",
            "your monthly payment will be exactly",
            "i promise this financing",
        ),
        "legal_advice": (
            "legally you should",
            "your legal rights are",
            "you should sue",
        ),
        "mechanical_diagnosis": (
            "this engine will last",
            "this car will never break down",
            "i guarantee no mechanical issues",
        ),
    },
    regex_guardrail_policies={
        "apr_promises": r"(?i)your\s+apr\s+(?:will|is\s+going\s+to)\s+be\s+\d",
        "credit_score_diagnosis": (
            r"(?i)(?:your|with\s+a)\s+credit\s+score\s+(?:of\s+)?\d+\s+"
            r"(?:means|guarantees|qualifies\s+you)"
        ),
    },
    redaction_message="[Removed: contains prohibited automotive advice]",
)
