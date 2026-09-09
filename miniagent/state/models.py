from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class ModelConfig(StrictModel):
    model: str = "microsoft/Phi-3.5-mini-instruct"
    revision: str = "main"
    max_new_tokens: int = Field(default=512, ge=1, le=4096)
    max_context_tokens: int = Field(default=4096, ge=128, le=32768)
    temperature: float = Field(default=0.0, ge=0, le=2)
    seed: int = Field(default=0, ge=0, le=2147483647)
    device: Literal["auto", "cpu", "cuda"] = "auto"
    local_files_only: bool = True
    max_generation_seconds: float = Field(default=120.0, gt=0)


class RunLimits(StrictModel):
    max_iterations: int = Field(default=100, ge=1)
    max_tool_calls: int = Field(default=80, ge=1)
    max_tokens: int = Field(default=100_000, ge=1)
    max_runtime_seconds: float = Field(default=3600.0, gt=0)
    max_consecutive_failures: int = Field(default=3, ge=1)
    max_parse_retries: int = Field(default=5, ge=0)
    max_blocked_actions: int = Field(default=3, ge=1)
    max_repeated_actions: int = Field(default=3, ge=1)
    max_replans: Annotated[int, Field(ge=0)] | Literal["unlimited"] = 20


class RuntimeOptions(StrictModel):
    file_output_format: Literal["json", "fenced"] = "fenced"
    repair_strategy: Literal["model", "rewrite"] = "model"
    execute_plan: bool = False
    planning_strategy: Literal["model", "files"] = "model"
    fresh_after: int = Field(default=3, ge=1)
    keep_best: bool = False
    repair_edit: Literal["file", "line"] = "file"
    repair_paths: list[str] = Field(default_factory=list, max_length=12)
    repair_functions: dict[str, list[str]] = Field(default_factory=dict)
    prompt_artifact: str | None = None
    file_tasks: dict[str, str] = Field(default_factory=dict)


class Checkpoint(StrictModel):
    passed: int = Field(ge=0)
    failures: int = Field(ge=0)
    files: dict[str, str]
    feedback: str


class ToolPolicy(StrictModel):
    write_paths: list[str] = Field(default_factory=list, max_length=30)
    commands: dict[str, list[str]] = Field(default_factory=dict)
    required_verifications: list[str] = Field(default_factory=list)
    command_timeout_seconds: float = Field(default=20.0, gt=0, le=120)

    @model_validator(mode="after")
    def check_commands(self):
        for name, argv in self.commands.items():
            if not name or not argv or any(not arg or "\x00" in arg for arg in argv):
                raise ValueError("Named commands require a nonempty argv without NUL")
        if not set(self.required_verifications).issubset(self.commands):
            raise ValueError("Required verifications must name configured commands")
        return self


class ToolAction(StrictModel):
    type: Literal["tool"]
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any]


class FinalAction(StrictModel):
    type: Literal["final"]
    answer: str = Field(min_length=1, max_length=8000)


class PlanStep(StrictModel):
    description: str = Field(min_length=1, max_length=240)
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any]


class PlanAction(StrictModel):
    type: Literal["plan"]
    steps: list[PlanStep] = Field(min_length=1, max_length=12)


Action = Annotated[ToolAction | FinalAction | PlanAction, Field(discriminator="type")]
ACTION_ADAPTER = TypeAdapter(Action)


class StepState(StrictModel):
    proposal: PlanStep
    observation_id: str | None = None


class ToolResult(StrictModel):
    success: bool
    output: str = ""
    error: str | None = None
    exit_code: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Observation(StrictModel):
    id: str
    iteration: int
    tool: str
    arguments: dict[str, Any]
    success: bool
    summary: str
    raw_output_ref: str
    result_hash: str
    exit_code: int | None = None
    verification_digest: str | None = None


class Metrics(StrictModel):
    llm_calls: int = 0
    parser_recoveries: int = 0
    invalid_actions: int = 0
    blocked_actions: int = 0
    loop_detections: int = 0
    failed_tools: int = 0
    successful_tools: int = 0


class AgentState(StrictModel):
    version: Literal[1] = 1
    run_id: str
    goal: str = Field(min_length=1, max_length=4000)
    status: Literal["running", "blocked", "completed", "failed"] = "running"
    started_at: float
    finished_at: float | None = None
    model_config_saved: ModelConfig = Field(default_factory=ModelConfig)
    limits: RunLimits = Field(default_factory=RunLimits)
    policy: ToolPolicy = Field(default_factory=ToolPolicy)
    options: RuntimeOptions = Field(default_factory=RuntimeOptions)
    iteration: int = Field(default=0, ge=0)
    steps: list[StepState] = Field(default_factory=list)
    # User-selected evidence requirements; the model cannot change these.
    required_reads: list[str] = Field(default_factory=list)
    verified_reads: list[str] = Field(default_factory=list)
    required_read_summaries: dict[str, str] = Field(default_factory=dict)
    verifications: dict[str, str] = Field(default_factory=dict)
    replans: int = 0
    needs_replan: bool = False
    last_action: str | None = None
    last_result_hash: str | None = None
    consecutive_failures: int = 0
    repeated_action_count: int = 0
    parse_failures: int = 0
    consecutive_blocks: int = 0
    token_budget_used: int = 0
    tool_calls: int = 0
    pending_action: ToolAction | None = None
    feedback: str | None = None
    repair_feedback: str | None = None
    last_failed_verification: str | None = None
    stalled_verifications: int = 0
    best_attempt: Checkpoint | None = None
    answer: str | None = None
    metrics: Metrics = Field(default_factory=Metrics)

    @property
    def current_step(self) -> StepState | None:
        return next((step for step in self.steps if step.observation_id is None), None)
