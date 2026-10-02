"""Class advisor backed by the Claude API through the official `anthropic` SDK (optional dependency).

Credentials come from the environment the SDK already understands: ANTHROPIC_API_KEY,
ANTHROPIC_AUTH_TOKEN, or a profile from `ant auth login`. RELABEL_CLAUDE_MODEL overrides the model.
"""
from __future__ import annotations

import base64
import os
from typing import Tuple

from .base import AdviceRequest, Advisor, AdvisorError, Suggestion, answer_schema, build_prompt, parse_answer

DEFAULT_MODEL = "claude-opus-5"
# models that accept server-side refusal fallbacks ("default" routes a declined request to the
# model Anthropic recommends for that refusal category instead of returning the refusal)
FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5", "claude-fable-5-1"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _image(jpeg: bytes) -> dict:
    return {"type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(jpeg).decode()}}


class ClaudeAPIAdvisor(Advisor):
    id = "claude-api"
    label = "Claude API"

    def __init__(self, model: str = None, timeout: float = 60.0):
        self.model = model or os.environ.get("RELABEL_CLAUDE_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self._client = None

    def availability(self) -> Tuple[bool, str]:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False, "pip install anthropic"
        has_env = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        has_profile = os.path.isdir(os.path.join(os.path.expanduser("~"), ".config", "anthropic"))
        if not (has_env or has_profile):
            return False, "set ANTHROPIC_API_KEY or run `ant auth login`, then restart Relabel"
        return True, self.model

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(timeout=self.timeout)
        return self._client

    def suggest(self, request: AdviceRequest) -> Suggestion:
        import anthropic

        content = [_image(request.crop_jpeg)]
        if request.context_jpeg:
            content.append(_image(request.context_jpeg))
        content.append({"type": "text", "text": build_prompt(request)})
        params = dict(
            model=self.model,
            max_tokens=2048,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": answer_schema(request.classes)}},
        )
        if self.model in FALLBACK_MODELS:
            params.update(betas=[FALLBACK_BETA], fallbacks="default")
        try:
            response = self._get_client().beta.messages.create(**params)
        except anthropic.AuthenticationError:
            raise AdvisorError("Claude API rejected the credentials: check ANTHROPIC_API_KEY or `ant auth login`.")
        except anthropic.PermissionDeniedError:
            raise AdvisorError(f"This API key cannot use {self.model}.")
        except anthropic.NotFoundError:
            raise AdvisorError(f"Model {self.model} was not found. Check RELABEL_CLAUDE_MODEL.")
        except anthropic.RateLimitError:
            raise AdvisorError("Claude API rate limit reached. Try again in a moment.")
        except anthropic.BadRequestError as e:
            raise AdvisorError(f"Claude API rejected the request: {e.message}")
        except anthropic.APIStatusError as e:
            raise AdvisorError(f"Claude API error {e.status_code}. Try again later.")
        except anthropic.APIConnectionError:
            raise AdvisorError("Could not reach the Claude API. Check the internet connection.")

        if response.stop_reason == "refusal":
            raise AdvisorError("Claude declined to classify this image.")
        text = next((b.text for b in response.content if b.type == "text"), "")
        return parse_answer(text, request.classes)
