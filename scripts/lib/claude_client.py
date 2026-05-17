"""ReasoningClient adapter for the Claude CLI (claude --print).

Lets the vendored /last30days planner.py + rerank.py use the local `claude` CLI
instead of an API provider (xAI, OpenAI, etc.). Free with a Claude subscription.

Usage:
    from .claude_client import build_provider
    provider = build_provider()  # returns None if `claude` not on PATH
    plan = planner.plan_query(..., provider=provider, model="claude-sonnet-4-6")
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from . import config, log
from .vendor.l30d.providers import ReasoningClient, extract_json


class ClaudeCliClient(ReasoningClient):
    """ReasoningClient backed by the local Claude CLI.

    Spawns `claude --print --model <model>` per call. stdin = prompt.
    """

    name = "claude-cli"

    def __init__(self, cli: str = "claude", timeout_seconds: int = 60) -> None:
        self.cli = cli
        self.timeout = timeout_seconds

    def generate_text(
        self,
        model: str,
        prompt: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        response_mime_type: str | None = None,
    ) -> str:
        if tools:
            log.debug("claude_cli_tools_ignored", note="tools arg is unused by claude CLI provider")
        cmd = [self.cli, "--print", "--model", model]
        try:
            r = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, timeout=self.timeout,
            )
        except FileNotFoundError as e:
            raise OSError(f"claude CLI not found at {self.cli!r}") from e
        except subprocess.TimeoutExpired as e:
            raise OSError(f"claude CLI timed out after {self.timeout}s") from e
        if r.returncode != 0:
            raise OSError(f"claude CLI exit {r.returncode}: {r.stderr[:300]}")
        return r.stdout.strip()


def build_provider() -> ClaudeCliClient | None:
    """Return a ClaudeCliClient if the CLI is on PATH, else None."""
    cli = config.env("CLAUDE_CLI", "claude") or "claude"
    if not shutil.which(cli):
        log.warn("claude_cli_not_found", cli=cli, hint="planner LLM expansion disabled")
        return None
    return ClaudeCliClient(cli=cli)
