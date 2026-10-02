"""What every class advisor shares: the request, the answer, the prompt and the answer parser.

An advisor looks at one selected box and says which of the project's classes it belongs to, with a
one-line reason. Concrete advisors (the Claude API, the Claude Code and Codex CLIs) differ only in
how they reach a model; they all ask the same question and are parsed the same way.
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class AdviceRequest:
    crop_jpeg: bytes                     # the selected box with some margin around it
    context_jpeg: Optional[bytes]        # the whole frame, downscaled, with the box outlined
    classes: List[str] = field(default_factory=list)
    current_class: str = ""


@dataclass(frozen=True)
class Suggestion:
    cls: str
    reason: str
    in_list: bool                        # False when the model answered with a class not in the list


class AdvisorError(Exception):
    """A failure worth showing to the user as-is (missing key, CLI not found, model declined...)."""


class Advisor(ABC):
    id: str = ""
    label: str = ""

    @abstractmethod
    def availability(self) -> Tuple[bool, str]:
        """(ready, hint). The hint tells the user how to set the advisor up when it is not ready."""

    @abstractmethod
    def suggest(self, request: AdviceRequest) -> Suggestion:
        """Ask the model. Raises AdvisorError with a user-facing message on failure."""


def build_prompt(request: AdviceRequest, image_refs: str = "the two images") -> str:
    classes = ", ".join(request.classes) if request.classes else "(no list given: use a short common noun)"
    current = f'It is currently labelled "{request.current_class}".' if request.current_class else ""
    return (
        f"You are checking a bounding-box label in a video annotation project. In {image_refs}, the "
        "first is a close crop of one annotated object and the second (if present) is the full frame "
        f"with that object's box outlined. {current}\n"
        f"Choose the single best class for the outlined object from this list: {classes}.\n"
        "Judge only the object inside the box. Reply with JSON only, no other text: "
        '{"class": "<one class from the list>", "reason": "<one short sentence, under 20 words>"}'
    )


def answer_schema(classes: List[str]) -> dict:
    cls = {"type": "string", "enum": list(classes)} if classes else {"type": "string"}
    return {"type": "object", "properties": {"class": cls, "reason": {"type": "string"}},
            "required": ["class", "reason"], "additionalProperties": False}


_JSON_OBJECT = re.compile(r"\{.*?\}", re.S)


def parse_answer(text: str, classes: List[str]) -> Suggestion:
    """Read {"class", "reason"} from a model reply, tolerating prose or code fences around it, and
    map the class onto the project's spelling (case-insensitive)."""
    data = None
    for candidate in [text.strip()] + _JSON_OBJECT.findall(text):
        try:
            obj = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(obj, dict) and "class" in obj:
            data = obj
            break
    if data is None:
        raise AdvisorError(f"The model did not answer in the expected format: {text.strip()[:160]}")
    answer = str(data.get("class", "")).strip()
    reason = " ".join(str(data.get("reason", "")).split())
    match = next((c for c in classes if c.lower() == answer.lower()), None)
    return Suggestion(cls=match or answer, reason=reason, in_list=match is not None)
