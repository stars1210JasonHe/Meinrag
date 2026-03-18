"""Hierarchical document classification taxonomy.

Three levels: Primary Category -> Domain -> Sub-Domain.

Taxonomy is loaded from data/taxonomy.json on first access.
If the file does not exist, a default taxonomy is written and used.
Users can edit data/taxonomy.json and restart the server to apply changes.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

TAXONOMY_PATH = Path("data/taxonomy.json")

_DEFAULT_TAXONOMY: dict[str, dict[str, list[str]]] = {
    "legal-compliance": {
        "contracts-agreements": [
            "employment-contract", "sales-contract", "service-agreement",
            "nda", "sla", "terms-conditions",
        ],
        "regulation-policy": [
            "regulatory-guidance", "compliance-policy",
            "standards-norms", "government-regulation",
        ],
        "litigation-disputes": [
            "court-decision", "claims-pleadings",
            "evidence-exhibits", "settlement",
        ],
        "intellectual-property": [
            "patent", "trademark", "copyright", "licensing-agreement",
        ],
        "legal-opinion": [
            "legal-memo", "attorney-letter", "due-diligence-report",
        ],
    },
    "finance-accounting": {
        "banking": [
            "bank-statement", "payment-confirmation",
            "loan-documents", "credit-card-statement",
        ],
        "tax": [
            "tax-return", "tax-notice", "vat-gst-documents", "tax-certificate",
        ],
        "corporate-finance": [
            "financial-statements", "audit-report", "budget-reports",
            "cash-flow-reports", "management-reports",
        ],
        "investment-markets": [
            "investment-research", "portfolio-statement",
            "prospectus", "trading-statement",
        ],
        "billing": [
            "invoice", "receipt", "expense-report", "purchase-reconciliation",
        ],
    },
    "business-operations": {
        "procurement-supply": [
            "purchase-order", "quotation", "delivery-note", "vendor-contract",
        ],
        "sales-customer": [
            "proposal", "statement-of-work",
            "customer-onboarding", "support-summary",
        ],
        "project-process": [
            "project-plan", "meeting-minutes",
            "process-documentation", "kpi-reports",
        ],
        "risk-governance": [
            "risk-assessment", "internal-audit",
            "board-materials", "policy-pack",
        ],
    },
    "technical-engineering": {
        "software-engineering": [
            "api-documentation", "architecture-design",
            "runbook", "security-report", "release-notes",
        ],
        "it-infrastructure": [
            "network-diagram", "system-specification",
            "incident-postmortem", "sop",
        ],
        "mechanical-manufacturing": [
            "cad-drawing", "process-sheet", "cam-setup",
            "quality-report", "material-specification",
        ],
        "electrical-electronics": [
            "circuit-diagram", "test-report",
            "compliance-certificate", "component-datasheet",
        ],
    },
    "medical-healthcare": {
        "clinical-documents": [
            "lab-results", "imaging-reports",
            "discharge-summary", "prescription",
        ],
        "insurance-claims": [
            "claim-form", "coverage-statement", "billing-statement",
        ],
        "medical-research": [
            "clinical-protocol", "investigator-brochure", "safety-report",
        ],
    },
    "government-administrative": {
        "immigration-residency": [
            "visa-documents", "residence-permit",
            "work-permit", "appointment-notice",
        ],
        "public-services": [
            "official-notice", "application-form",
            "certificate", "registration-document",
        ],
        "tax-social-security": [
            "tax-office-letters", "social-insurance-records", "benefits-notice",
        ],
    },
    "hr-personal": {
        "employment": [
            "resume-cv", "offer-letter",
            "employment-contract", "performance-review",
        ],
        "payroll": [
            "payslip", "bonus-statement", "annual-income-statement",
        ],
        "personal-records": [
            "identity-documents", "utility-bills",
            "insurance-policy", "education-certificate",
        ],
    },
    "marketing-media": {
        "brand-content": [
            "brochure", "press-release", "product-sheet", "pitch-deck",
        ],
        "market-intelligence": [
            "market-report", "competitor-analysis", "customer-survey",
        ],
    },
    "education-research": {
        "teaching-materials": [
            "lecture-notes", "slides", "assignments", "course-handbook",
        ],
        "academic-administration": [
            "transcript", "degree-certificate", "enrollment-letter",
        ],
    },
    "research-scientific": {
        "fundamental-science": [
            "physics", "mathematics", "chemistry", "astronomy", "geoscience",
        ],
        "computer-science-ai": [
            "machine-learning", "nlp", "computer-vision",
            "distributed-systems", "cybersecurity", "software-engineering-research",
        ],
        "engineering-research": [
            "materials-science", "control-systems",
            "aerospace-engineering", "robotics", "manufacturing-cam-research",
        ],
        "life-science-biomedical": [
            "molecular-biology", "neuroscience", "genomics",
            "public-health", "clinical-trials-research",
        ],
        "environmental-energy": [
            "climate-research", "renewable-energy",
            "sustainability-studies", "environmental-engineering",
        ],
        "social-science-economics": [
            "economics-research", "finance-research",
            "psychology", "policy-research", "legal-research",
        ],
        "interdisciplinary-science": [
            "complex-systems", "computational-social-science",
            "history-of-science", "philosophy-of-science",
        ],
    },
    "other": {
        "unclassified": [
            "low-ocr-quality", "mixed-content", "unreadable-documents",
        ],
    },
}


def _load_taxonomy() -> dict[str, dict[str, list[str]]]:
    """Load taxonomy from JSON file, creating default if missing."""
    if TAXONOMY_PATH.exists():
        try:
            with open(TAXONOMY_PATH, encoding="utf-8") as f:
                taxonomy = json.load(f)
            logger.info("Taxonomy loaded from %s (%d categories)", TAXONOMY_PATH, len(taxonomy))
            return taxonomy
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load %s: %s — using default taxonomy", TAXONOMY_PATH, e)
            return _DEFAULT_TAXONOMY

    # Write default taxonomy for user to customize
    try:
        TAXONOMY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TAXONOMY_PATH, "w", encoding="utf-8") as f:
            json.dump(_DEFAULT_TAXONOMY, f, indent=2, ensure_ascii=False)
        logger.info("Default taxonomy written to %s", TAXONOMY_PATH)
    except OSError as e:
        logger.warning("Could not write default taxonomy: %s", e)

    return _DEFAULT_TAXONOMY


# Loaded once at import time. Restart server to pick up changes.
TAXONOMY: dict[str, dict[str, list[str]]] = _load_taxonomy()

PRIMARY_CATEGORIES: list[str] = list(TAXONOMY.keys())
ALL_DOMAINS: list[str] = [
    domain for domains in TAXONOMY.values() for domain in domains
]
DEFAULT_COLLECTION = "other"
