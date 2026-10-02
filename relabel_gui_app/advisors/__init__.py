"""Ask an AI model which class a selected box belongs to. See base.py for the shared contract."""
from .base import AdviceRequest, Advisor, AdvisorError, Suggestion
from .registry import AdvisorRegistry, default_advisors

__all__ = ["AdviceRequest", "Advisor", "AdvisorError", "Suggestion", "AdvisorRegistry", "default_advisors"]
