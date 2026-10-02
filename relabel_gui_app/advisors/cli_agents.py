"""Class advisors that run a coding-agent CLI already installed and logged in on this machine, so
no API key is needed: Claude Code (`claude -p`) and OpenAI Codex (`codex exec`).

Both follow the same steps (template method): write the images to a temporary folder, run the CLI
with the prompt on stdin, read its final reply, parse it. Subclasses only say how to call the CLI
and where its reply ends up.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from abc import abstractmethod
from typing import List, Optional, Tuple

from .base import AdviceRequest, Advisor, AdvisorError, Suggestion, build_prompt, parse_answer


class CliAgentAdvisor(Advisor):
    executable = ""
    install_hint = ""

    def __init__(self, timeout: float = 180.0):
        self.timeout = timeout

    def _path(self) -> Optional[str]:
        return shutil.which(self.executable)

    def availability(self) -> Tuple[bool, str]:
        path = self._path()
        return (True, path) if path else (False, self.install_hint)

    @abstractmethod
    def command(self, exe: str, images: List[str], workdir: str) -> List[str]:
        """argv for one run; the prompt is sent on stdin."""

    @abstractmethod
    def reply(self, stdout: str, workdir: str) -> str:
        """The model's final message, from the CLI output."""

    def suggest(self, request: AdviceRequest) -> Suggestion:
        exe = self._path()
        if not exe:
            raise AdvisorError(f"{self.label} is not installed: {self.install_hint}")
        with tempfile.TemporaryDirectory(prefix="relabel-ask-") as workdir:
            images = [self._write(workdir, "crop.jpg", request.crop_jpeg)]
            if request.context_jpeg:
                images.append(self._write(workdir, "frame.jpg", request.context_jpeg))
            prompt = build_prompt(request, image_refs=" and ".join(images))
            try:
                done = subprocess.run(self.command(exe, images, workdir), input=prompt, capture_output=True,
                                      text=True, encoding="utf-8", cwd=workdir, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                raise AdvisorError(f"{self.label} did not answer within {int(self.timeout)} s.")
            except OSError as e:
                raise AdvisorError(f"Could not start {self.label}: {e}")
            if done.returncode != 0:
                detail = (done.stderr or done.stdout).strip().splitlines()[-1:] or ["no output"]
                raise AdvisorError(f"{self.label} failed: {detail[0][:200]}")
            return parse_answer(self.reply(done.stdout, workdir), request.classes)

    @staticmethod
    def _write(folder: str, name: str, data: bytes) -> str:
        path = os.path.join(folder, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path


class ClaudeCodeAdvisor(CliAgentAdvisor):
    id = "claude-code"
    label = "Claude Code"
    executable = "claude"
    install_hint = "install Claude Code and log in (`claude`), then restart Relabel"

    def command(self, exe, images, workdir):
        # headless mode; only the Read tool is allowed, which is how Claude Code looks at images
        return [exe, "-p", "--output-format", "json", "--allowedTools", "Read", "--max-turns", "4"]

    def reply(self, stdout, workdir):
        try:
            result = json.loads(stdout)
        except ValueError:
            return stdout
        if result.get("is_error"):
            raise AdvisorError(f"Claude Code reported an error: {str(result.get('result', ''))[:200]}")
        return str(result.get("result", ""))


class CodexAdvisor(CliAgentAdvisor):
    id = "codex"
    label = "OpenAI Codex"
    executable = "codex"
    install_hint = "install the Codex CLI and log in (`codex login`), then restart Relabel"

    def command(self, exe, images, workdir):
        argv = [exe, "exec", "--skip-git-repo-check", "--sandbox", "read-only",
                "--output-last-message", os.path.join(workdir, "answer.txt")]
        for path in images:
            argv += ["--image", path]
        return argv + ["-"]                                   # "-": read the prompt from stdin

    def reply(self, stdout, workdir):
        path = os.path.join(workdir, "answer.txt")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        return stdout
