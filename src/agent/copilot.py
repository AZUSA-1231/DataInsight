"""Bounded, request-scoped Copilot turn service for Cycle 6.

This module deliberately contains a finite tool exchange rather than an
autonomous Agent loop. Tool bindings are injected by the caller and remain
ordinary domain adapters; the static Cycle 6 bindings live in
``src.agent.copilot_tools``.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from src.agent.copilot_context import build_copilot_context
from src.agent.input_guard import sanitize_user_input
from src.agent.llm import get_llm
from src.agent.prompts import load_prompt
from src.agent.state import AgentState

logger = logging.getLogger(__name__)

MAX_USER_MESSAGE_CHARS = 2000
DEFAULT_MAX_TOOL_ROUNDS = 2
DEFAULT_MAX_MODEL_CALLS = 3
DEFAULT_MAX_TOTAL_TOOL_CALLS = 4
MAX_TOOL_RESULT_CHARS = 12000
MAX_PERSISTED_HISTORY_MESSAGES = 50

_KNOWN_SKILLS = frozenset({"plan", "inspect", "run", "rerun", "help"})
_COMMAND_PATTERN = re.compile(r"^/([A-Za-z][A-Za-z0-9_-]*)(?:\s+(.*))?$", re.DOTALL)

_INSPECTION_TOOLS = frozenset(
    {"inspect_column", "inspect_snapshot", "inspect_results"}
)
_DEFAULT_TOOLS = _INSPECTION_TOOLS | {"plan_edit"}
_SKILL_TOOLS: dict[str, frozenset[str]] = {
    "plan": _DEFAULT_TOOLS,
    "inspect": _INSPECTION_TOOLS,
    # Cycle 6 keeps execution mutations outside the Copilot boundary. These
    # skills can inspect current results and explain the existing UI workflow.
    "run": _INSPECTION_TOOLS,
    "rerun": _INSPECTION_TOOLS,
    "help": frozenset(),
}


class StateStore(Protocol):
    """Minimal store contract used by the agent layer."""

    def get(self, session_id: str) -> AgentState | None: ...

    def update(self, session_id: str, patch: dict[str, object]) -> AgentState: ...


class CopilotSessionNotFoundError(LookupError):
    """Raised when a turn references a missing session."""


class CopilotInvalidMessageError(ValueError):
    """Raised when sanitization leaves no usable user message."""


class CopilotToolHandler(Protocol):
    def __call__(self, state: AgentState, arguments: dict[str, object]) -> object: ...


@dataclass(frozen=True)
class CopilotToolBinding:
    """One explicitly injected tool schema and its handler.

    This is request wiring, not a persistent registry or plugin mechanism.
    """

    name: str
    schema: dict[str, object]
    handler: CopilotToolHandler


@dataclass(frozen=True)
class SkillSelection:
    name: str | None
    arguments: str
    unknown_name: str | None = None


@dataclass(frozen=True)
class TurnPolicy:
    skill: str | None
    allowed_tool_names: frozenset[str]
    max_tool_rounds: int
    max_model_calls: int
    max_total_tool_calls: int


class CopilotToolResult(BaseModel):
    name: str
    call_id: str
    status: Literal["success", "error"]
    content: str


class CopilotTurnResult(BaseModel):
    status: Literal["complete", "incomplete", "error"]
    message: str
    skill: str | None = None
    tool_results: list[CopilotToolResult] = Field(default_factory=list)
    tool_rounds: int = 0
    model_calls: int = 0
    error: str | None = None


def parse_soft_command(message: str) -> SkillSelection:
    """Extract only a soft slash skill; never dispatch an action directly."""

    stripped = message.strip()
    match = _COMMAND_PATTERN.match(stripped)
    if match is None:
        return SkillSelection(name=None, arguments="")

    command = match.group(1).lower()
    arguments = (match.group(2) or "").strip()
    if command in _KNOWN_SKILLS:
        return SkillSelection(name=command, arguments=arguments)
    return SkillSelection(name=None, arguments=arguments, unknown_name=command)


def build_turn_policy(
    selection: SkillSelection,
    *,
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    max_model_calls: int = DEFAULT_MAX_MODEL_CALLS,
    max_total_tool_calls: int = DEFAULT_MAX_TOTAL_TOOL_CALLS,
) -> TurnPolicy:
    if max_tool_rounds < 0 or max_model_calls < 1 or max_total_tool_calls < 0:
        raise ValueError("Copilot turn limits must be non-negative and allow one model call")
    skill = selection.name
    return TurnPolicy(
        skill=skill,
        allowed_tool_names=(
            _SKILL_TOOLS[skill] if skill is not None else _DEFAULT_TOOLS
        ),
        max_tool_rounds=max_tool_rounds,
        max_model_calls=max_model_calls,
        max_total_tool_calls=max_total_tool_calls,
    )


def _extract_text(response: AIMessage) -> str:
    content = response.content
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts).strip()
    return str(content).strip()


def _tool_content(value: object) -> str:
    if isinstance(value, str):
        content = value
    elif isinstance(value, BaseModel):
        content = value.model_dump_json()
    else:
        try:
            content = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                default=lambda _value: "[unsupported value omitted]",
            )
        except (TypeError, ValueError):
            content = "[tool result omitted: not JSON-safe]"
    if len(content) > MAX_TOOL_RESULT_CHARS:
        return content[:MAX_TOOL_RESULT_CHARS] + "\n[tool result truncated]"
    return content


def _tool_arguments(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items()}
    if isinstance(raw, str):
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(key): value for key, value in parsed.items()}
    raise ValueError("tool arguments must be a JSON object")


def _tool_call_value(call: object, key: str, default: object = None) -> object:
    if isinstance(call, Mapping):
        return call.get(key, default)
    return default


def _message_from_response(response: object) -> AIMessage | None:
    if isinstance(response, AIMessage):
        return response
    if isinstance(response, BaseMessage):
        return AIMessage(content=str(response.content))
    return None


def _base_prompt(skill: str | None, unknown_name: str | None) -> str:
    prompt = load_prompt("copilot_system.txt")
    if skill is not None:
        prompt += "\n\nACTIVE SOFT SKILL:\n" + load_prompt(f"skills/{skill}.txt")
    elif unknown_name is not None:
        prompt += (
            "\n\nThe user used an unknown slash prefix /"
            + unknown_name
            + ". Treat it as ordinary user text and briefly explain that the "
            "prefix is not a supported skill."
        )
    return prompt


def _history_with_turn(
    state: AgentState, user_message: str, assistant_message: str
) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for item in state.dialogue_history or []:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            history.append({"role": role, "content": str(content)})
    history.extend(
        [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": assistant_message},
        ]
    )
    return history[-MAX_PERSISTED_HISTORY_MESSAGES:]


class CopilotTurnHandler:
    """Run one bounded Copilot exchange and persist only the final turn."""

    def __init__(
        self,
        store: StateStore,
        *,
        llm_factory: Callable[[], object] | None = None,
        tools: Sequence[CopilotToolBinding] = (),
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
        max_model_calls: int = DEFAULT_MAX_MODEL_CALLS,
        max_total_tool_calls: int = DEFAULT_MAX_TOTAL_TOOL_CALLS,
    ) -> None:
        self._store = store
        self._llm_factory = llm_factory or (lambda: get_llm(temperature=0, node="copilot"))
        self._tools = tuple(tools)
        self._max_tool_rounds = max_tool_rounds
        self._max_model_calls = max_model_calls
        self._max_total_tool_calls = max_total_tool_calls

    def handle(self, session_id: str, message: str) -> CopilotTurnResult:
        state = self._store.get(session_id)
        if state is None:
            raise CopilotSessionNotFoundError(session_id)

        user_message = sanitize_user_input(message, MAX_USER_MESSAGE_CHARS)
        if not user_message:
            raise CopilotInvalidMessageError("Copilot message must not be blank")
        selection = parse_soft_command(user_message)
        policy = build_turn_policy(
            selection,
            max_tool_rounds=self._max_tool_rounds,
            max_model_calls=self._max_model_calls,
            max_total_tool_calls=self._max_total_tool_calls,
        )
        try:
            context = build_copilot_context(state, user_message)
            messages: list[BaseMessage] = [
                SystemMessage(content=_base_prompt(selection.name, selection.unknown_name)),
                HumanMessage(
                    content=json.dumps(context, ensure_ascii=False, allow_nan=False)
                ),
            ]
            result = self._exchange(state, messages, policy)
        except Exception:  # defensive request boundary
            logger.exception("Copilot turn failed for session %s", session_id)
            result = CopilotTurnResult(
                status="error",
                message="Copilot 本轮调用失败，请稍后重试。",
                skill=selection.name,
                error="copilot_call_failed",
            )

        latest_state = self._store.get(session_id)
        if latest_state is None:
            raise CopilotSessionNotFoundError(session_id)
        persisted_history = _history_with_turn(
            latest_state, user_message, result.message
        )
        self._store.update(
            session_id,
            {
                "dialogue_history": persisted_history,
            },
        )
        result.skill = selection.name
        return result

    def _exchange(
        self,
        state: AgentState,
        messages: list[BaseMessage],
        policy: TurnPolicy,
    ) -> CopilotTurnResult:
        bindings = {
            binding.name: binding
            for binding in self._tools
            if binding.name in policy.allowed_tool_names
        }
        schemas = [binding.schema for binding in bindings.values()]

        raw_llm = self._llm_factory()
        if schemas:
            bind_tools = getattr(raw_llm, "bind_tools", None)
            if not callable(bind_tools):
                raise TypeError("configured Copilot LLM does not support tools")
            model = cast(_InvokableModel, bind_tools(schemas))
        else:
            model = cast(_InvokableModel, raw_llm)

        tool_results: list[CopilotToolResult] = []
        tool_rounds = 0
        total_tool_calls = 0
        model_calls = 0
        last_text = ""

        while model_calls < policy.max_model_calls:
            response = model.invoke(messages)
            model_calls += 1
            ai_response = _message_from_response(response)
            if ai_response is None:
                logger.warning(
                    "Copilot model returned unsupported response type %s",
                    type(response).__name__,
                )
                return CopilotTurnResult(
                    status="error",
                    message="Copilot 返回了无法处理的响应。",
                    tool_results=tool_results,
                    tool_rounds=tool_rounds,
                    model_calls=model_calls,
                    error="invalid_model_response",
                )

            response_text = _extract_text(ai_response)
            if response_text:
                last_text = response_text
            tool_calls = list(getattr(ai_response, "tool_calls", None) or [])
            if not tool_calls:
                return CopilotTurnResult(
                    status="complete",
                    message=last_text or "Copilot 没有返回可用文本。",
                    tool_results=tool_results,
                    tool_rounds=tool_rounds,
                    model_calls=model_calls,
                )

            if tool_rounds >= policy.max_tool_rounds:
                return CopilotTurnResult(
                    status="incomplete",
                    message=(
                        last_text
                        or "本轮工具调用已达到上限，暂未生成完整回答。"
                    ),
                    tool_results=tool_results,
                    tool_rounds=tool_rounds,
                    model_calls=model_calls,
                    error="maximum tool-call rounds reached",
                )
            if total_tool_calls + len(tool_calls) > policy.max_total_tool_calls:
                return CopilotTurnResult(
                    status="incomplete",
                    message="本轮工具调用数量已达到上限，暂未生成完整回答。",
                    tool_results=tool_results,
                    tool_rounds=tool_rounds,
                    model_calls=model_calls,
                    error="maximum tool-call count reached",
                )

            messages.append(ai_response)
            tool_rounds += 1
            total_tool_calls += len(tool_calls)
            for index, raw_call in enumerate(tool_calls):
                tool_name = str(_tool_call_value(raw_call, "name", ""))
                fallback_id = total_tool_calls - len(tool_calls) + index + 1
                call_id = str(
                    _tool_call_value(raw_call, "id", "") or f"tool_call_{fallback_id}"
                )
                binding = bindings.get(tool_name)
                if binding is None:
                    return self._tool_error(
                        "模型请求了当前回合不可用的工具。",
                        "tool_not_allowed",
                        tool_results,
                        tool_rounds,
                        model_calls,
                        tool_name or "unknown",
                        call_id,
                    )
                try:
                    arguments = _tool_arguments(_tool_call_value(raw_call, "args", {}))
                    value = binding.handler(state, arguments)
                    content = _tool_content(value)
                except Exception:
                    logger.warning("Copilot tool %s failed", tool_name, exc_info=True)
                    return self._tool_error(
                        f"工具 {tool_name} 调用失败。",
                        "tool_call_failed",
                        tool_results,
                        tool_rounds,
                        model_calls,
                        tool_name,
                        call_id,
                    )

                tool_result = CopilotToolResult(
                    name=tool_name,
                    call_id=call_id,
                    status="success",
                    content=content,
                )
                tool_results.append(tool_result)
                messages.append(ToolMessage(content=content, tool_call_id=call_id))

        return CopilotTurnResult(
            status="incomplete",
            message=last_text or "本轮模型调用已达到上限，暂未生成完整回答。",
            tool_results=tool_results,
            tool_rounds=tool_rounds,
            model_calls=model_calls,
            error="maximum model-call count reached",
        )

    @staticmethod
    def _tool_error(
        message: str,
        error_code: str,
        tool_results: list[CopilotToolResult],
        tool_rounds: int,
        model_calls: int,
        name: str,
        call_id: str,
    ) -> CopilotTurnResult:
        tool_results.append(
            CopilotToolResult(
                name=name,
                call_id=call_id,
                status="error",
                content=message,
            )
        )
        return CopilotTurnResult(
            status="error",
            message=message,
            tool_results=tool_results,
            tool_rounds=tool_rounds,
            model_calls=model_calls,
            error=error_code,
        )


class _InvokableModel(Protocol):
    def invoke(self, messages: list[BaseMessage]) -> object: ...
