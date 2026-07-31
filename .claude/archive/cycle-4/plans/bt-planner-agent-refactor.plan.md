# Plan: BT & Planner — Intelligent Agent Refactoring

**Source**: 用户反思 — 当前 BT/Planner 是"反AI"的流水线，需重构为真正的智能体
**Complexity**: Large
**Depends on**: Cycle 3 M1+M2+M3 (complete), `bt-planner-unified-stream.plan.md` (archived, superseded)

## Summary

当前 BT 被强制在每轮对话同时扮演"聊天伙伴"和"JSON 打印机"两个角色——这是精神分裂式的设计。Planner 被强制接受上游的结构化单据，没有自己的阅读理解能力。两者是流水线上的工位，而非同一张桌子两侧的同事。

本次重构将 BT 和 Planner 改造为**两个真正的 AI Agent**：
- **BT Agent**：对话型智能体，可反问用户、自查数据、自主判断何时"理解够了"，通过 **tool calling**（`submit_planner_instruction`）提交精确的无损指令
- **Planner Agent**：工程型智能体，阅读完整对话历史 + BT 指令 + 数据全貌，自主推理并产出可执行 Plan

两个 Agent 各自拥有 **skill-level system prompt**（~300 行，分层结构），稳定、长篇幅、不动态拼接。动态信息（columns、data_profile、history）作为 user message 注入。

## Architecture

```
用户发消息
      │
      ▼
┌─────────────────────────────────────────────────────┐
│  BT Agent (Business Track)                          │
│                                                     │
│  System Prompt: ~300 lines, layered                 │
│  ┌ PERSONA   — 你是谁、性格、工作方式                │
│  ├ CONTEXT   — 系统环境、你能看到什么                 │
│  ├ TOOLS     — submit_planner_instruction            │
│  ├ RULES     — 硬约束（不编造列名、不承诺不可行的分析）│
│  ├ GUIDANCE  — 软约束（何时追问、如何引导用户）        │
│  └ WORKFLOW  — S1-S4 场景导航                        │
│                                                     │
│  行为：                                              │
│  - 自然对话（可反问、可追问、可澄清）                  │
│  - 查阅 data_profile（tool: inspect_column）          │
│  - 自主判断"够了" → tool call: submit_instruction     │
│  - 不会在每轮对话都产出结构化输出                       │
└─────────────────────────────────────────────────────┘
      │
      │  BT 调用 submit_planner_instruction
      │  → 前端弹出确认 UI
      │  → 用户确认
      │
      ▼
┌─────────────────────────────────────────────────────┐
│  Planner Agent                                       │
│                                                     │
│  System Prompt: ~250 lines, layered                  │
│  ┌ PERSONA   — 你是谁、工作方式                       │
│  ├ CONTEXT   — 输入源（对话历史+BT指令+数据+workspace）│
│  ├ RULES     — 硬约束                                 │
│  ├ GUIDANCE  — 推理方法论                             │
│  └ WORKFLOW  — 阅读→推理→验证→产 Plan                 │
│                                                     │
│  输入（全量，自己阅读理解）：                           │
│  - 完整对话历史（BT ↔ 用户）                           │
│  - BT 的 PlannerInstruction（精确但可质疑）             │
│  - data_profile + unified_columns                    │
│  - 当前 workspace Plan（如存在）                       │
│                                                     │
│  输出：Plan（cleaning + N units + alignment_notes）    │
└─────────────────────────────────────────────────────┘
```

**关键区别**：

| 维度 | 旧（流水线） | 新（Agent） |
|------|------------|-----------|
| BT 输出时机 | 每轮强制产 JSON | BT 自己决定何时提交 instruction |
| BT 对话能力 | 3-6 句 natural language（被限制） | 真正的多轮对话，可追问、反问 |
| BT↔Planner 传递 | 格式严密但信息压缩的 JSON | 自然语言 brief + 结构化 hints + 对话全史 |
| Planner 推理 | "执行这些指令" | "阅读全貌，自己理解，自己决定" |
| Prompt | 每轮动态拼接 ~150 行 | 稳定 system prompt ~300 行 + 动态 user message |
| 错误处理 | 格式不对 → instruction=None（静默丢失） | BT 是 agent，自己会修正 |

## Patterns to Mirror

| Category | Source | Pattern |
|----------|--------|---------|
| Node signature | `src/agent/nodes/business_track.py:316` | `xxx_node(state) -> dict[str, object]` |
| LLM factory | `src/agent/llm.py:18` | `get_llm(temperature=0, node="xxx")` |
| State immutability | `src/agent/nodes/planner.py:279` | `return {"plan": plan}` — never mutate |
| Pydantic models | `src/agent/state.py:71-99` | `BaseModel` with strict field types |
| Tool/function calling | LangChain `bind_tools()` / OpenAI-compatible tool calling | New pattern — not yet in codebase |
| Dialogue route SSE | `src/api/routes/dialogue.py:83-173` | `StreamingResponse` + `text/event-stream` |
| Agent loop | New pattern — `while not done: llm.invoke() → check tool_calls` | No existing mirror |
| System prompt loading | New pattern — `prompts/` directory with `.md` or `.txt` files | No existing mirror |
| Error handling | `src/agent/nodes/business_track.py:361-363` | try/except → `return {"error": "..."}` |

## Files to Change

| File | Action | Why |
|------|--------|-----|
| `src/agent/prompts/__init__.py` | CREATE | Prompt loader utility |
| `src/agent/prompts/bt_system.txt` | CREATE | BT Agent system prompt (~300 lines, English) |
| `src/agent/prompts/planner_system.txt` | CREATE | Planner Agent system prompt (~250 lines, English) |
| `src/agent/tools.py` | CREATE | Tool definitions: `submit_planner_instruction`, `inspect_column` |
| `src/agent/state.py` | UPDATE | `PlannerInstruction` 字段调整（更精确）；移除冗余字段 |
| `src/agent/nodes/business_track.py` | REWRITE | BT Agent: system prompt + tool calling + agent loop logic |
| `src/agent/nodes/planner.py` | REWRITE | Planner Agent: system prompt + 全量上下文输入 + 自主推理 |
| `src/agent/graph.py` | UPDATE | 适配新的 node 签名（BT 产出 instruction 而非直接产 Plan） |
| `src/api/routes/dialogue.py` | UPDATE | Agent loop 编排；SSE 事件流适配（thinking/text/tool_call/confirm） |
| `src/api/routes/workspace.py` | UPDATE | `generate_plan` 适配新的 Planner 签名 |
| `src/api/schemas.py` | UPDATE | 新增 SSE agent 事件 schema；确认响应 schema |
| `src/__main__.py` | UPDATE | CLI 适配（或 CLI 保留旧路径，agent 路径仅 API） |
| `tests/conftest.py` | UPDATE | 新增 BT Agent 和 Planner Agent 的 mock fixtures |
| `tests/test_business_track.py` | UPDATE | Agent loop 测试；tool calling 测试；反问场景测试 |
| `tests/test_planner.py` | UPDATE | 全量上下文输入测试；自主推理质量测试 |
| `tests/test_graph.py` | UPDATE | 适配新的 graph 路由 |
| `tests/api/test_dialogue.py` | UPDATE | Agent SSE 事件流测试 |
| `tests/api/test_workspace.py` | UPDATE | 适配 generate_plan |

### DELETE

| Item | Why |
|------|-----|
| `_build_bt_prompt()` | 替换为稳定的 system prompt + 动态 user message |
| `_build_planner_prompt()` | 替换为稳定的 system prompt + 动态 user message |
| `_build_planner_prompt_with_feedback()` | feedback 改为对话历史的一部分，Planner 自己理解 |
| `_build_planner_review_prompt()` | 审核逻辑并入 Planner 的统一推理 |
| `_parse_bt_output()` | BT 改用 tool calling，不再需要三段式字符串解析 |
| `AnalysisIntent` model | 被 `PlannerInstruction` 完全替代（保留字段但在 state 中标记 deprecated） |
| `_INSTRUCTION_SCHEMA` (in bt prompt) | Tool schema 替代 prompt-embedded JSON schema |
| `_PLAN_SCHEMA` (in planner prompt) | Planner system prompt 内置 |

## Tasks

### Task 0: Prompt Loader (`src/agent/prompts/__init__.py`)

- **Action**: 创建简单的 prompt 加载工具
  ```python
  from pathlib import Path

  _PROMPTS_DIR = Path(__file__).parent

  def load_prompt(name: str) -> str:
      """Load a system prompt from the prompts directory."""
      path = _PROMPTS_DIR / name
      if not path.exists():
          raise FileNotFoundError(f"Prompt file not found: {path}")
      return path.read_text(encoding="utf-8")
  ```
- **Mirror**: 项目现有的文件加载模式（`inspection_script.py` 通过 `Path` 加载）
- **Validate**: `python -c "from src.agent.prompts import load_prompt; p = load_prompt('bt_system.txt'); assert len(p) > 500"`

### Task 1: BT Agent System Prompt (`src/agent/prompts/bt_system.txt`)

~300 行，分层结构，英文撰写。核心内容：

```
=== PERSONA ===
You are a senior business analyst at DataInsight. You are the user's first
point of contact. Your job is to understand what the user wants to learn from
their data, ask clarifying questions when needed, and then write a precise
instruction for the Planner agent who will execute the analysis.

You are curious, thorough, and honest. You don't rush to conclusions. You
ask questions before you commit to a plan. You treat the user as a colleague
— you respect their domain knowledge but you bring data expertise to the table.

=== CONTEXT ===
You have access to:
- The user's current message and full conversation history
- The uploaded dataset's column names (if data has been uploaded)
- Detailed data profile: column types, null rates, unique counts, sample values
- The current workspace Plan (if the user has been building one)

The Planner agent will receive your instruction along with the full
conversation history and data profile. Write your instruction for a
technically-skilled colleague — precise about columns and methods, but
you don't need to specify every implementation detail.

=== HOW YOU RESPOND ===
You have TWO ways to respond. You choose which one is appropriate:

1. **Conversational response** (default):
   - Ask clarifying questions
   - Explain what you see in the data
   - Suggest analytical directions
   - Guide the user toward a clear goal
   - Be natural, not scripted. Match the user's language.

2. **Tool call: submit_planner_instruction** (when ready):
   - Use ONLY when you are confident you understand what needs to be done
   - The instruction should be thorough — this is your handoff document
   - You will NOT get another chance to talk to the Planner
   - After submitting, your role in this analysis cycle is complete

=== WHEN TO ASK QUESTIONS ===
Ask questions when:
- The user's request is vague ("analyze sales" — by what? over what period?)
- Multiple interpretations are possible ("compare regions" — which metric?)
- Data quality issues need user judgment ("column X has 40% missing — exclude or impute?")
- The user seems to want too many things at once (guide them to prioritize)
- You're unsure whether to modify existing work or start fresh

Do NOT ask questions when:
- The request is clear and specific
- The data can obviously support the request
- The user is clearly in a hurry or has said "just do it"

=== TOOLS ===
[Tool: submit_planner_instruction — schema and field descriptions]
[Tool: inspect_column — query specific column statistics]

=== RULES ===
1. NEVER invent column names. Use EXACT names from the data.
2. NEVER promise analyses the data can't support. If data is insufficient, say so.
3. When column quality is poor, flag it in your instruction — don't silently proceed.
4. Match the user's language. If they speak Chinese, respond in Chinese.
5. NEVER output JSON, code fences, or structured data in conversational responses.
6. Be honest about uncertainty. "I'm not sure" is better than a wrong assumption.
7. Respect existing workspace. Don't discard the user's work unless they ask.

=== GUIDANCE ===
- A good analysis plan has 1-5 units. Don't over-engineer.
- Consider this progression: describe → compare → diagnose → predict.
- When the user says "analyze X", mentally ask: by what dimension? over what time? compared to what?
- Pay attention to data types when suggesting methods:
  - Numeric columns → statistics, regression, clustering
  - Categorical columns → grouping, segmentation, frequency analysis
  - Datetime columns → trend, seasonality, period-over-period comparison
- If the user mentions a column that doesn't exist, suggest the closest match.
- If the workspace already has units, map the user's words to specific unit_ids.

=== WORKFLOW BY SCENARIO ===

S1 — No data: Guide the user to upload data. Be welcoming but brief.

S2 — Fresh analysis (data, no plan):
  1. Understand the user's goal
  2. If vague, ask 1-2 clarifying questions
  3. If clear, briefly explain what you'll instruct the Planner to do
  4. Call submit_planner_instruction

S3 — Revision (data + plan):
  1. Map the user's words to specific units in the workspace
  2. If ambiguous which unit they mean, ASK
  3. Confirm the scope of changes
  4. Call submit_planner_instruction with is_revision=true + target_unit_ids

S4 — Proactive (data + plan, no message):
  1. Look at the workspace — what's missing?
  2. Suggest 1-2 natural next steps
  3. Wait for user response (don't call submit_planner_instruction yet)

S5 — Feedback from report:
  - The user is responding to a generated report
  - Their message may reference charts, numbers, or conclusions
  - Treat this as S3 (revision) — map their feedback to specific units
```

- **Validate**: `python -c "from src.agent.prompts import load_prompt; p = load_prompt('bt_system.txt'); assert 'PERSONA' in p; assert 'submit_planner_instruction' in p"`

### Task 2: Planner Agent System Prompt (`src/agent/prompts/planner_system.txt`)

~250 行，分层结构。

```
=== PERSONA ===
You are a senior data engineer at DataInsight. Your job is to take a business
analyst's instruction — along with the full conversation history and data
profile — and produce a concrete, executable analysis Plan.

You are the final decision-maker on HOW to execute. The Business Track analyst
captures WHAT the user wants. You decide HOW to do it — which methods, which
columns, what cleaning strategy, what edge cases to watch for.

=== CONTEXT ===
You receive:
1. **Conversation History** — the full dialogue between the user and the
   Business Track analyst. This contains the user's original words, the
   analyst's questions and clarifications, and the user's answers.
2. **PlannerInstruction** — a structured brief from the analyst with
   core_question, analysis_type, column assignments, unit suggestions,
   revision context, and analytical suggestions.
3. **Data Profile** — detailed statistics for every column: dtype, null_count,
   null_pct, unique_count, unique_pct, sample head rows.
4. **Unified Columns** — the complete list of column names in the dataset.
5. **Workspace Plan** — the current Plan if one exists (for revisions).

=== YOUR OUTPUT ===
A single JSON object — the Plan — with:
- `cleaning`: one PlanUnit (unit_id=0) for data quality handling
- `units`: 1-5 PlanUnits for analysis, each with purpose/model/related_fields/cautious
- `alignment_notes`: honest assessment of what the data can/cannot answer

=== RULES ===
1. NEVER invent column names. Every `related_fields` entry must be from the data.
2. Every unit must have CONCRETE, data-aware cautious notes. "注意数据质量" is
   not acceptable. Write: "region 列有 30% 空值 — 按地区分组的结果可能有偏"
3. If data quality prevents a requested analysis, SAY SO in alignment_notes.
4. Don't pad. If the user wants one thing, output one unit. Max 5 units.
5. The cleaning unit must explain WHY specific cleaning actions are needed.
6. Use specific model names: "sklearn.linear_model.LinearRegression", not "回归".
7. Chinese column names and purposes are fine — match the data's language.

=== GUIDANCE ===
- **Read the conversation history first.** The user may have discussed trade-offs
  or constraints with the analyst that aren't in the structured instruction.
- **Trust the data over the instruction.** If the analyst says "use linear
  regression on category" but the target is categorical, note the conflict
  and suggest an appropriate method instead.
- **Check null rates.** If a key column has high nulls, note the bias risk.
- **Consider data types:**
  - int/float → statistical methods, regression, clustering, correlation
  - string/category/object → grouping, segmentation, frequency, chi-square
  - datetime → trend, seasonality, period-over-period, rolling windows
- **The conversation history is as important as the instruction.**
  The analyst may have discussed nuances that didn't fit into the structured
  format. The user's original words carry intent that JSON can't capture.
- **When revising:** only modify units listed in target_unit_ids. Preserve
  other units exactly. Add new units if the analyst suggests them.
- **Be honest in alignment_notes.** If the data can only partially answer
  the question, say so. If assumptions are shaky, flag them.

=== WORKFLOW ===
1. Read the conversation history — understand the user's journey
2. Read the analyst's instruction — what specifically needs to be done
3. Study the data profile — what's possible, what's risky
4. Check the workspace Plan — what exists, what needs to change
5. Reason holistically:
   - Are the analyst's unit suggestions valid given the data?
   - Are there missing cautious notes to add?
   - Is the cleaning strategy appropriate?
   - Can the data actually answer the core question?
6. Produce the Plan JSON

=== OUTPUT FORMAT ===
[Plan JSON schema — same as current _PLAN_SCHEMA but with richer field descriptions]
```

- **Validate**: `python -c "from src.agent.prompts import load_prompt; p = load_prompt('planner_system.txt'); assert 'PERSONA' in p"`

### Task 3: Tool Definitions (`src/agent/tools.py`)

定义 BT Agent 可用的 tools（LangChain tool format，兼容 OpenAI function calling）：

```python
from langchain_core.tools import tool
from pydantic import BaseModel, Field

class SubmitInstructionInput(BaseModel):
    """Schema for submit_planner_instruction tool."""
    core_question: str = Field(description="The user's business question, restated precisely")
    analysis_type: str = Field(description="One of: descriptive, diagnostic, predictive, comparative, trend")
    complexity: str = Field(default="moderate", description="simple, moderate, or complex")
    target_columns: list[str] = Field(default_factory=list, description="EXACT column names for target/dependent variables")
    group_by: list[str] = Field(default_factory=list, description="EXACT column names for grouping/segmentation")
    filter_hint: str | None = Field(default=None, description="Any data filter condition")
    unit_suggestions: list[dict] = Field(default_factory=list, description="Pre-structured analysis units with purpose/model/related_fields/cautious")
    is_revision: bool = Field(default=False, description="Whether this modifies existing workspace units")
    target_unit_ids: list[int] = Field(default_factory=list, description="Which unit IDs are being revised")
    revision_notes: str | None = Field(default=None, description="What changed and why")
    suggestions: list[dict] = Field(default_factory=list, description="Additional analytical suggestions")
    caution_notes: str | None = Field(default=None, description="Analytical pitfalls to be aware of")
    instruction_nl: str = Field(description="Natural language summary for the Planner — this is the MOST important field. Write a thorough brief (5-10 sentences) explaining the user's intent, context, edge cases discussed, and why you made the choices you did. This is your handoff document to a colleague.")


@tool(args_schema=SubmitInstructionInput)
def submit_planner_instruction(
    core_question: str,
    analysis_type: str,
    complexity: str = "moderate",
    target_columns: list[str] = [],
    group_by: list[str] = [],
    filter_hint: str | None = None,
    unit_suggestions: list[dict] = [],
    is_revision: bool = False,
    target_unit_ids: list[int] = [],
    revision_notes: str | None = None,
    suggestions: list[dict] = [],
    caution_notes: str | None = None,
    instruction_nl: str = "",
) -> str:
    """Submit a structured analysis instruction to the Planner agent.

    Call this tool ONLY when you are confident you fully understand what the
    user wants. After calling this, your analysis phase ends — the Planner
    takes over. You will not get another chance to talk to the Planner.

    The instruction_nl field is the most important part — write a thorough
    natural-language brief explaining the full context.
    """
    # Tool body is a no-op — the agent loop intercepts the tool call
    return "Instruction submitted. Planner will take over from here."


class InspectColumnInput(BaseModel):
    column_name: str = Field(description="EXACT column name to inspect")


@tool(args_schema=InspectColumnInput)
def inspect_column(column_name: str) -> str:
    """Look up detailed statistics for a specific column in the dataset.

    Returns dtype, null count, null percentage, unique count, unique percentage,
    and sample values for the requested column.
    """
    # This is resolved at runtime by the agent loop which has access to data_profile
    return f"Column '{column_name}' statistics will be resolved at runtime."


BT_TOOLS = [submit_planner_instruction, inspect_column]
```

- **Validate**: `python -c "from src.agent.tools import BT_TOOLS; assert len(BT_TOOLS) == 2"`

### Task 4: State Model Refinement (`src/agent/state.py`)

- **PlannerInstruction 增加字段**：
  ```python
  instruction_nl: str = ""  # Natural language brief — the most important field
  ```
- **AgentState 字段清理**：
  - `analysis_intent` 保留但标记 `Deprecated: use planner_instruction instead`
  - `dialogue_history` 升级为首要字段（Planner 依赖此字段理解上下文）
- **移除冗余**：不需要新增其他字段。当前 state 已足够承载 Agent 模式。

- **Validate**: `python -c "from src.agent.state import AgentState, PlannerInstruction; pi = PlannerInstruction(core_question='test', analysis_type='descriptive', instruction_nl='test brief'); assert pi.instruction_nl == 'test brief'"`

### Task 5: BT Agent Node (`src/agent/nodes/business_track.py`)

重写 `business_track_node` 为 Agent 模式：

```python
def business_track_node(state: AgentState) -> dict[str, object]:
    """BT Agent: intelligent conversational analyst with tool calling.

    Uses a stable system prompt + dynamic user context. The LLM decides
    whether to respond conversationally (ask questions, explain) or to
    call submit_planner_instruction (when understanding is sufficient).

    Reads: state.user_requirement, state.dialogue_history, state.unified_columns,
           state.data_profile, state.plan, state.feedback
    Writes: state.planner_instruction (if tool called), state.dialogue_history,
            state.analysis_intent (deprecated compat)
    """
```

核心逻辑：
1. **加载 system prompt**：`load_prompt("bt_system.txt")`
2. **构建 user context**（动态信息注入，非 prompt 拼接）：
   ```
   [DATA CONTEXT]
   Columns: {unified_columns}
   Data Profile Summary: {shape, column names + dtypes}
   Workspace Plan: {plan_json or "none"}
   Feedback: {feedback or "none"}

   [CONVERSATION HISTORY]
   {formatted dialogue history}

   [CURRENT MESSAGE]
   {user_requirement}
   ```
3. **LLM 调用**：`get_llm(temperature=0, node="business_track").bind_tools(BT_TOOLS).invoke([system_msg, user_msg])`
4. **处理响应**：
   - 如果 LLM 返回 `AIMessage` 且有 `tool_calls` → 提取 `submit_planner_instruction` 参数 → 返回 `{"planner_instruction": ..., "_bt_response": explanation_text, "_bt_tool_called": True}`
   - 如果 LLM 返回纯文本 → 返回 `{"_bt_response": text, "_bt_tool_called": False}`
5. **不调用 `_parse_bt_output()`** — tool calling 返回的就是结构化数据，无需字符串解析

**`_bt_response` 和 `_bt_tool_called` 是非 state 元数据**（前缀 `_`），供 dialogue route 用于 SSE 事件编排，不写入 AgentState。

- **Mirror**: 现有的 `business_track_node` 签名 (`state -> dict[str, object]`) + LangChain tool calling API
- **Validate**: `pytest -v -k "business_track" tests/`

### Task 6: Planner Agent Node (`src/agent/nodes/planner.py`)

重写 `planner_node`：

```python
def planner_node(state: AgentState) -> dict[str, object]:
    """Planner Agent: reads full context, reasons holistically, produces Plan.

    Input (all read from state, nothing forced):
    - Full conversation history (state.dialogue_history)
    - BT's PlannerInstruction (state.planner_instruction)
    - Data profile (state.data_profile)
    - Unified columns (state.unified_columns)
    - Current workspace Plan (state.plan)

    Output: Plan (state.plan)
    """
```

核心逻辑：
1. **加载 system prompt**：`load_prompt("planner_system.txt")`
2. **构建 user context**：
   ```
   [FULL CONVERSATION HISTORY]
   {formatted dialogue history between user and Business Track analyst}

   [PLANNER INSTRUCTION FROM BUSINESS TRACK]
   {planner_instruction.model_dump_json()}
   - instruction_nl (analyst's brief — READ THIS FIRST):
   {planner_instruction.instruction_nl}

   [DATA PROFILE]
   {data_profile_json}

   [AVAILABLE COLUMNS]
   {unified_columns}

   [CURRENT WORKSPACE PLAN]
   {workspace_plan_json or "No existing plan — generate from scratch"}
   ```
3. **LLM 调用**：`get_llm(temperature=0, node="planner").invoke([system_msg, user_msg])`
4. **JSON 提取 + 解析**：保留 `_extract_json()` + `_parse_plan_from_json()`（已成熟，无需改动）
5. **不再有** `_build_planner_prompt` 的 if/elif 分支 — Planner 自己从全量上下文中判断

- **Mirror**: 现有的 `planner_node` 签名 + JSON 解析工具函数
- **Validate**: `pytest -v -k "planner" tests/`

### Task 7: Dialogue Route Refactoring (`src/api/routes/dialogue.py`)

适配 BT Agent 的 tool calling 模式：

**SSE 事件流重构**：

```
旧事件流：token → instruction → done (action=generate|revise|recommend)

新事件流（BT 纯对话）：
  thinking → token → done (action=chat)

新事件流（BT 调用 tool）：
  thinking → token → tool_call (name=submit_planner_instruction, args={...})
  → done (action=confirm, instruction={...})
```

**`send_message` (POST /dialogue)**：
- 调用 `business_track_node(state)`
- 如果 `_bt_tool_called` → 返回 PlannerInstruction + action="confirm"
- 如果纯文本 → 返回文本 + action="chat"

**`stream_intent` (GET /dialogue/stream)**：
- 调用 `business_track_node(state)` — 但需要流式能力
- **关键设计决策**：BT Agent 的 system prompt + user context 较长（~4000 tokens），不适合用 streaming 逐 token 返回 + 同时等待 tool call 判断。**BT 的 LLM 调用使用非流式 `invoke()`**，然后对 explanation 文本做逐字符 SSE 推流（模拟打字效果）。这是可行的因为 BT 响应文本通常在 50-300 字。
- SSE 事件顺序：
  1. `event: status` → `{"status": "thinking"}`
  2. `event: token` × N（逐字符推 BT 的 conversational 文本）
  3. 如果 BT 调用了 tool：
     - `event: tool_call` → `{"name": "submit_planner_instruction", "args": {...}}`
     - `event: done` → `{"action": "confirm", "instruction": {...}}`
  4. 如果 BT 纯文本：
     - `event: done` → `{"action": "chat"}`

**前端对应行为**：
- `action=chat` → 消息气泡 + 输入框保持活跃（BT 在等待用户回复）
- `action=confirm` → 消息气泡 + 弹出确认卡片："BT 建议：{core_question}。是否生成分析计划？" [确认] [继续对话]

- **Validate**: `pytest -v -k "test_dialogue" tests/api/`

### Task 8: Workspace Route Adaptation (`src/api/routes/workspace.py`)

`POST /plan/generate` 适配新的 Planner 签名：

- 检查 `state.planner_instruction is not None` → 否则 400 "No instruction from Business Track yet"
- 调用 `planner_node(state)` → 返回 Plan
- 成功后 `planner_instruction` 不清空（保留作为审计追踪）

- **Validate**: `pytest -v -k "test_workspace" tests/api/`

### Task 9: Graph Adaptation (`src/agent/graph.py`)

CLI 的 `graph.invoke()` 是图级一次性调用，与 Agent 的交互模式不完全匹配。处理方式：

- **CLI 模式**：保留 `START → data_track → business_track → planner → ...` 全图。CLI 场景下 BT 没有多轮对话机会，需要在一次调用中产出 instruction 然后 Planner 立即消费。
- **实现**：`business_track_node` 在 CLI 场景下（无 dialogue_history 或首个空消息）直接调用 tool（不反问）→ 上游保证 instruction 产出
- Graph 结构不变（节点和边保持不变），只是 node 内部实现变了

- **Validate**: `pytest -v -k "graph" tests/`

### Task 10: CLI Adaptation (`src/__main__.py`)

- CLI 的 `_handle_plan_modification` 已不再使用 `draft_plan`（M2 清理），无需改动
- CLI 的 state 构造无需 `planner_instruction`（BT node 会自产）
- `_display_plan` 保持不变

- **Validate**: `python -c "from src.__main__ import main; print('import OK')"`

### Task 11: Schema Updates (`src/api/schemas.py`)

新增 SSE 相关 schema：

```python
class DialogueStreamResponse(BaseModel):
    """SSE event types emitted during dialogue streaming."""
    action: str  # "chat" | "confirm"
    instruction: dict[str, object] | None = None  # Present when action=confirm
    full_text: str = ""  # The complete conversational text
```

`GeneratePlanRequest` 已有 `instruction` 字段，无需改动。

- **Validate**: `python -c "from src.api.schemas import DialogueStreamResponse; print('OK')"`

### Task 12: Test Suite Updates

#### 12a. `tests/conftest.py`
- 新增 `bt_system_prompt` fixture（mock `load_prompt` 返回简化版 prompt）
- 新增 `planner_system_prompt` fixture
- 新增 `tool_call_llm` fixture（mock LLM 返回带 tool_calls 的 AIMessage）
- 新增 `sample_dialogue_history` fixture

#### 12b. `tests/test_business_track.py`
- **重写**：不再测试 `_build_bt_prompt`（函数删除）
- 新增测试：
  - `test_bt_agent_conversational_response` → LLM 返回纯文本，不调用 tool
  - `test_bt_agent_submits_instruction` → LLM 调用 submit_planner_instruction
  - `test_bt_agent_with_dialogue_history` → 多轮对话上下文正确注入
  - `test_bt_agent_fallback_on_tool_error` → tool call 格式异常时的 graceful fallback
  - `test_bt_agent_inspects_column` → 调用 inspect_column tool
  - `test_bt_agent_revision_scenario` → workspace 存在 + 修订消息 → is_revision=true
  - `test_bt_agent_system_prompt_loaded` → 验证 system prompt 被正确加载和使用

#### 12c. `tests/test_planner.py`
- 删除/重写：所有依赖 `_build_planner_prompt` 签名的测试
- 新增测试：
  - `test_planner_agent_reads_conversation_history` → 验证对话历史注入 prompt
  - `test_planner_agent_reads_instruction_nl` → 验证 instruction_nl 优先阅读提示
  - `test_planner_agent_falls_back_without_instruction` → 无 instruction 时回退到 analysis_intent
  - `test_planner_agent_revision_merges_units` → 修订模式正确合并 unit
  - `test_planner_agent_system_prompt_loaded` → 验证 system prompt 被正确加载

#### 12d. `tests/api/test_dialogue.py`
- 更新 SSE 事件流断言（新事件类型：status/tool_call/confirm）
- 新增：`test_stream_intent_tool_call_event` → 验证 tool_call 事件格式
- 新增：`test_send_message_returns_chat_action` → 纯对话返回 action=chat
- 新增：`test_send_message_returns_confirm_action` → tool call 返回 action=confirm

#### 12e. `tests/api/test_workspace.py`
- 更新 `test_generate_plan`：需要 state 中有 planner_instruction
- 新增：`test_generate_plan_without_instruction_returns_400`

#### 12f. `tests/test_graph.py`
- 更新集成测试：BT node 现在依赖 system prompt + tool calling
- Graph 路由测试保持不变（边没变）

## Validation

```bash
# System prompt loading
python -c "from src.agent.prompts import load_prompt; assert len(load_prompt('bt_system.txt')) > 500; assert len(load_prompt('planner_system.txt')) > 500"

# Tool definitions
python -c "from src.agent.tools import BT_TOOLS, submit_planner_instruction; assert len(BT_TOOLS) == 2"

# Unit tests per module
pytest -v -k "business_track" tests/
pytest -v -k "planner" tests/
pytest -v -k "graph" tests/
pytest -v -k "test_dialogue" tests/api/
pytest -v -k "test_workspace" tests/api/

# Full suite
pytest -v

# Type check
mypy src/

# Lint
ruff check . && ruff format . --check

# Manual smoke test
uvicorn src.api.app:app --reload &
# Browser: create session → upload CSV → send message → verify BT responds naturally
# → verify confirm UI appears when BT calls tool → verify Planner produces Plan
```

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Tool calling 在某些 LLM provider 上不可靠（格式错误、幻觉参数） | Medium | `inspect_column` 的 schema 简单（单字段）；`submit_planner_instruction` 有完整 fallback：解析失败时返回 `{"_bt_tool_called": False, "_bt_response": raw_text}` |
| System prompt 过长导致 BT 延迟增加（~3000 tokens system + ~2000 tokens context） | Medium | 使用 prompt caching（OpenAI/Anthropic 均支持）；system prompt 稳定不变 → 每次请求仅增量部分重新计算 |
| BT 反问太多，用户体验变差（"我问了它一个问题，它又问我三个"） | Medium | System prompt 的 GUIDANCE 中明确"ask 1-2 clarifying questions, not an interrogation"；实际效果需用户测试验证 |
| CLI 模式与 Agent 模式的行为差异（CLI 无多轮对话机会） | Low | BT node 检测上下文：`if not state.dialogue_history and not state.plan: → 直接 tool call（不反问）` |
| 旧测试大面积失败（`_build_bt_prompt`、`_build_planner_prompt` 删除） | High | 这些是内部函数，tests 已在通过 mock LLM 间接测试。重写测试的 mock 策略（mock `get_llm().invoke()` 返回含 tool_calls 的 AIMessage） |
| LangChain tool calling API 与项目当前 `BaseChatModel` 抽象兼容性 | Low | 项目已使用 `langchain-openai` 的 `ChatOpenAI`，原生支持 `.bind_tools()`；非 OpenAI provider 需验证 |

## Acceptance

- [ ] BT 系统 prompt 加载成功，包含 PERSONA/CONTEXT/TOOLS/RULES/GUIDANCE/WORKFLOW 六层
- [ ] Planner 系统 prompt 加载成功，包含 PERSONA/CONTEXT/RULES/GUIDANCE/WORKFLOW 五层
- [ ] BT Agent 可在纯对话模式下回复（不调用 tool）
- [ ] BT Agent 可反问用户（"你想按地区还是按时间分析？"）
- [ ] BT Agent 可在理解充分后调用 `submit_planner_instruction` tool
- [ ] `submit_planner_instruction` tool call 被正确解析为 `PlannerInstruction`
- [ ] `instruction_nl` 字段包含 BT 的自然语言 brief（无损传输的核心）
- [ ] Planner Agent 读取完整对话历史 + instruction + data → 自主推理产出 Plan
- [ ] Planner 能识别 instruction 与 data 的冲突（如列名不存在）并在 alignment_notes 中标注
- [ ] Dialogue SSE 事件流正确：`status → token → [tool_call] → done`
- [ ] 前端 `action=confirm` 时弹出确认 UI，`action=chat` 时保持对话态
- [ ] CLI `python -m src` 仍可一次性全图运行（BT 直接 tool call，不反问）
- [ ] 所有现有测试通过或合理改写（`pytest -v`）
- [ ] Type check 通过（`mypy src/`）
- [ ] Lint 通过（`ruff check .`）
- [ ] `_build_bt_prompt`、`_parse_bt_output`、`_build_planner_prompt` 等旧函数已删除
- [ ] `AnalysisIntent` 标记 deprecated，Planner 优先使用 `PlannerInstruction`
