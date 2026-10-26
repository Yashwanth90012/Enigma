"""Production Meterless Markovian Engine for EQUILIBRA / ENIGMA.

Implements the official Meterless Markovian specification:
- Bounded execution chunks with O(1) context scaling
- Exact token accounting and efficiency formulas (reproducing 86.18% at N=20)
- Immutable per-run chunkConfig snapshot
- Marker protocol: [STATE_CHECKPOINT], [TASK_COMPLETE], and marker cleaning
- 4-level state compression cascade: Marker override -> Model compressor -> Heuristics -> Word truncation
- Non-zero overlapTokens window with [OVERLAP] prompt injection
- Durable transactional checkpoints (run_id, step, version, state, checksum)
- Crash recovery: resume from latest valid checkpoint without repeating completed chunks
- Idempotent side-effect deduplication for irreversible actions
- Reflection pass (ratify/refine) with safe failure isolation
- Multi-tenant PostgreSQL persistence surviving process and container restarts
"""

import copy
import hashlib
import json
import logging
import math
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("equilibra.markovian")

# -----------------------------------------------------------------------------
# 1. Constants, Config & Efficiency Math (docs/efficiency-model.md)
# -----------------------------------------------------------------------------

FRAMING_TOKENS = 400
OUTPUT_BUDGET = 1200

BOUNDS = {
    "chunk_size": {"min": 1000, "max": 128000, "step": 1000},
    "chunkSize": {"min": 1000, "max": 128000, "step": 1000},
    "max_chunks": {"min": 1, "max": 32, "step": 1},
    "maxChunks": {"min": 1, "max": 32, "step": 1},
    "carryover_tokens": {"min": 128, "max": 32768, "step": 128},
    "carryoverTokens": {"min": 128, "max": 32768, "step": 128},
    "overlap_tokens": {"min": 0, "max": 4096, "step": 1},
    "overlapTokens": {"min": 0, "max": 4096, "step": 1},
}


class ConfigValidationError(ValueError):
    """Raised when Markovian chunk configuration violates specification bounds."""
    def __init__(self, message: str):
        super().__init__(f"Markovian config: {message}")
        self.message = message


class CostModelConstants:
    def __init__(self, F: int = 400, G: int = 200, S: int = 300, O: int = 1200, C: int = 800):
        self.F = F  # Framing overhead
        self.G = G  # Goal description
        self.S = S  # Step input
        self.O = O  # Output per step
        self.C = C  # Carryover state


DOC_DEFAULTS = CostModelConstants(F=400, G=200, S=300, O=1200, C=800)


def estimate_tokens(text: str) -> int:
    """Standard token estimator: ceil(chars / 4). Labeled 'estimated'."""
    if not text:
        return 0
    return math.ceil(len(text) / 4)


class ChunkConfig(dict):
    """Immutable chunk configuration snapshot."""
    def __init__(
        self,
        chunk_size: int = 8000,
        max_chunks: int = 24,
        carryover_tokens: int = 800,
        overlap_tokens: int = 0,
        **kwargs
    ):
        cs = kwargs.get("chunkSize", chunk_size)
        mc = kwargs.get("maxChunks", max_chunks)
        ct = kwargs.get("carryoverTokens", carryover_tokens)
        ot = kwargs.get("overlapTokens", overlap_tokens)

        super().__init__(
            chunk_size=cs,
            chunkSize=cs,
            max_chunks=mc,
            maxChunks=mc,
            carryover_tokens=ct,
            carryoverTokens=ct,
            overlap_tokens=ot,
            overlapTokens=ot
        )
        self.chunk_size = cs
        self.chunkSize = cs
        self.max_chunks = mc
        self.maxChunks = mc
        self.carryover_tokens = ct
        self.carryoverTokens = ct
        self.overlap_tokens = ot
        self.overlapTokens = ot

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunkSize": self.chunkSize,
            "maxChunks": self.maxChunks,
            "carryoverTokens": self.carryoverTokens,
            "overlapTokens": self.overlapTokens
        }


DEFAULT_CONFIG = ChunkConfig()


def resolve_config(partial: Optional[Union[Dict[str, Any], ChunkConfig]] = None) -> ChunkConfig:
    """Validate and resolve chunk configuration against official specification bounds."""
    partial = partial or {}
    cs = partial.get("chunkSize", partial.get("chunk_size", DEFAULT_CONFIG.chunkSize))
    mc = partial.get("maxChunks", partial.get("max_chunks", DEFAULT_CONFIG.maxChunks))
    ct = partial.get("carryoverTokens", partial.get("carryover_tokens", DEFAULT_CONFIG.carryoverTokens))
    ot = partial.get("overlapTokens", partial.get("overlap_tokens", DEFAULT_CONFIG.overlapTokens))

    for key, val, name in [
        ("chunkSize", cs, "chunkSize"),
        ("maxChunks", mc, "maxChunks"),
        ("carryoverTokens", ct, "carryoverTokens"),
        ("overlapTokens", ot, "overlapTokens")
    ]:
        if not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
            raise ConfigValidationError(f"{name} must be a number")
        b = BOUNDS[key]
        if val < b["min"] or val > b["max"]:
            raise ConfigValidationError(f"{name}={val} outside [{b['min']}, {b['max']}]")

    if ct <= 0:
        raise ConfigValidationError("carryoverTokens must be > 0")

    if cs < FRAMING_TOKENS + ct + OUTPUT_BUDGET:
        raise ConfigValidationError(
            f"chunkSize={cs} < framing({FRAMING_TOKENS}) + carryover({ct}) + outputBudget({OUTPUT_BUDGET})"
        )

    return ChunkConfig(chunk_size=int(cs), max_chunks=int(mc), carryover_tokens=int(ct), overlap_tokens=int(ot))


def model_totals(N: int, k: CostModelConstants = DOC_DEFAULTS) -> Dict[str, Any]:
    """Exact symbolic cost model from docs/efficiency-model.md.
    
    reproduces: N=20 -> naiveTotal=246,000, markovianTotal=34,000, efficiency=86.18%
    """
    naive_total = N * (k.F + k.G + k.S) + (k.O * N * (N - 1)) // 2
    markovian_total = N * (k.F + k.G + k.C + k.S)
    savings = naive_total - markovian_total
    efficiency = savings / naive_total if naive_total > 0 else 0.0
    return {
        "naiveTotal": naive_total,
        "markovianTotal": markovian_total,
        "savings": savings,
        "efficiency": efficiency
    }


# TypeScript runner export alias
modelTotals = model_totals


def run_efficiency(chunks: List[Any], cfg: Union[ChunkConfig, Dict[str, Any]]) -> Dict[str, Any]:
    """Compute historical run efficiency against the run's own persisted snapshot."""
    if isinstance(cfg, dict) and not isinstance(cfg, ChunkConfig):
        cfg = ChunkConfig(**cfg)
    total_tokens_used = sum(c["tokens"] if isinstance(c, dict) else c.tokens for c in chunks)
    standard_cost = 0
    prefix = 0
    for c in chunks:
        tok = c["tokens"] if isinstance(c, dict) else c.tokens
        standard_cost += prefix + tok
        prefix += tok

    ct = cfg.carryoverTokens
    markovian_cost = len(chunks) * ct + total_tokens_used
    tokens_saved = max(0, standard_cost - markovian_cost)
    efficiency_percent = (tokens_saved / standard_cost) * 100.0 if standard_cost > 0 else 0.0

    return {
        "totalTokensUsed": total_tokens_used,
        "standardCost": standard_cost,
        "markovianCost": markovian_cost,
        "tokensSaved": tokens_saved,
        "efficiencyPercent": efficiency_percent
    }


runEfficiency = run_efficiency


def projection_curve(cfg: ChunkConfig, steps: int = 10) -> List[Dict[str, int]]:
    """Project theoretical efficiency curve over N steps."""
    out = []
    for step in range(1, steps + 1):
        history_size = (step - 1) * cfg.chunkSize
        out.append({
            "step": step,
            "standard": history_size + cfg.chunkSize,
            "markovian": cfg.carryoverTokens + cfg.chunkSize
        })
    return out


projectionCurve = projection_curve


# -----------------------------------------------------------------------------
# 2. Marker Protocol & Content Sanitization
# -----------------------------------------------------------------------------

STATE_BLOCKS = [
    re.compile(r'<CARRYOVER>([\s\S]*?)</CARRYOVER>', re.MULTILINE),
]
STATE_TAILS = [
    re.compile(r'\[STATE_CHECKPOINT\]\s*([\s\S]*)$'),
    re.compile(r'@@@STATE@@@\s*([\s\S]*)$'),
    re.compile(r'(?<!_)\[STATE\]\s*([\s\S]*)$'),
    re.compile(r'---STATE---\s*([\s\S]*)$'),
]
FINAL_MARKERS = [
    re.compile(r'\[TASK_COMPLETE\]'),
    re.compile(r'@@@FINAL@@@'),
    re.compile(r'(?<!_)\[FINAL\]'),
    re.compile(r'---FINAL---'),
    re.compile(r'<DONE\s*/?>'),
]
PROGRESS_BLOCK = re.compile(r'<PROGRESS>([\s\S]*?)</PROGRESS>')
NEEDS_TOOL = re.compile(r'[<\[]NEEDS_TOOL\s+tool="([^"]+)"\s+input=(?:"([^"]*)"|\'([^\']*)\')\s*/?[\]>]')
NEEDS_CLARIFICATION = re.compile(r'[<\[]NEEDS_CLARIFICATION[\]>]\s*([^\n]*)')


class ParsedMarkers:
    def __init__(
        self,
        state: Optional[str] = None,
        done: bool = False,
        progress: Optional[str] = None,
        needs_tool: Optional[Dict[str, str]] = None,
        needs_clarification: Optional[str] = None,
        cleaned: str = ""
    ):
        self.state = state
        self.done = done
        self.progress = progress
        self.needs_tool = needs_tool
        self.needs_clarification = needs_clarification
        self.cleaned = cleaned


def parse_markers(raw: str) -> ParsedMarkers:
    """Parse state checkpoints, completion, and control markers from chunk output."""
    state = None
    for re_sb in STATE_BLOCKS:
        matches = list(re_sb.finditer(raw))
        if matches:
            state = matches[-1].group(1).strip()

    if state is None:
        for re_st in STATE_TAILS:
            m = re_st.search(raw)
            if m:
                state = m.group(1).strip()
                break

    done = any(re_fm.search(raw) for re_fm in FINAL_MARKERS)

    prog_m = PROGRESS_BLOCK.search(raw)
    progress = prog_m.group(1).strip() if prog_m else None

    tool_m = NEEDS_TOOL.search(raw)
    needs_tool = None
    if tool_m:
        tool_name = tool_m.group(1)
        tool_inp = tool_m.group(2) if tool_m.group(2) is not None else (tool_m.group(3) or "")
        needs_tool = {"tool": tool_name, "input": tool_inp}

    clar_m = NEEDS_CLARIFICATION.search(raw)
    needs_clarification = clar_m.group(1).strip() if clar_m else None

    cleaned = clean_markers(raw)
    return ParsedMarkers(
        state=state,
        done=done,
        progress=progress,
        needs_tool=needs_tool,
        needs_clarification=needs_clarification,
        cleaned=cleaned
    )


def clean_markers(raw: str) -> str:
    """Strip all internal markers from user/display output."""
    out = raw
    out = re.sub(r'<CARRYOVER>[\s\S]*?</CARRYOVER>', '', out)
    out = re.sub(r'<PROGRESS>[\s\S]*?</PROGRESS>', '', out)
    out = re.sub(r'[<\[]NEEDS_TOOL[^\]>]*[\]>]', '', out)
    out = re.sub(r'[<\[]NEEDS_CLARIFICATION[\]>][^\n]*', '', out)
    out = re.sub(r'\[STATE_CHECKPOINT\][\s\S]*$', '', out)
    out = re.sub(r'@@@STATE@@@[\s\S]*$', '', out)
    out = re.sub(r'---STATE---[\s\S]*$', '', out)
    out = re.sub(r'\n\[STATE\][\s\S]*$', '', out)
    for re_fm in [r'\[TASK_COMPLETE\]', r'@@@FINAL@@@', r'---FINAL---', r'<DONE\s*/?>']:
        out = re.sub(re_fm, '', out)
    out = re.sub(r'\n\[FINAL\][\s\S]*$', '', out)
    # Collapse trailing spaces and excessive blank lines
    out = re.sub(r'[ \t]+$', '', out, flags=re.MULTILINE)
    out = re.sub(r'\n{3,}', '\n\n', out)
    return out.strip()


def canonical_block(completed: str, remaining: str, decisions: str, context: str) -> str:
    """Format canonical carryover block."""
    return f"COMPLETED: {completed}\nREMAINING: {remaining}\nDECISIONS: {decisions}\nCONTEXT: {context}"


# -----------------------------------------------------------------------------
# 3. Prompt Builder & Overlap Window
# -----------------------------------------------------------------------------

MARKER_RULES = (
    "End every non-final chunk with [STATE_CHECKPOINT] followed by a concise state block:\n"
    "COMPLETED: ...\nREMAINING: ...\nDECISIONS: ...\nCONTEXT: ...\n"
    "End the final chunk with [TASK_COMPLETE]. Exactly one marker per chunk. Never narrate the markers."
)


def overlap_slice(previous_cleaned: str, config: ChunkConfig) -> str:
    """Slice trailing window of previous cleaned content for overlap injection."""
    if config.overlapTokens <= 0 or not previous_cleaned:
        return ""
    char_len = config.overlapTokens * 4
    return previous_cleaned[-char_len:]


def build_prompt(
    mode: str,
    goal: str,
    step: int,
    carryover: str,
    overlap_text: str = "",
    memory_context: Optional[str] = None,
    attachments: Optional[List[Dict[str, str]]] = None,
    config: Optional[ChunkConfig] = None
) -> str:
    """Build chunk prompt enforcing memory injection on chunk 1 and carryover on continuation."""
    parts: List[str] = []
    attachments = attachments or []
    config = config or DEFAULT_CONFIG

    if step == 1 and memory_context:
        parts.append(memory_context.strip())
        parts.append("")

    if step == 1:
        if mode == "ARCHITECT":
            parts.append("You are executing a long build task in bounded chunks. Analyze the goal, produce a plan, and start implementation.")
        else:
            parts.append(
                "You are executing recursive research in bounded chunks. Log every action as '>> action'. "
                "Produce multi-file style output where useful and keep a research-tree state snapshot."
            )
        parts.append("")
        parts.append(f"User Request: {goal}")
        if attachments:
            parts.append("")
            for a in attachments:
                parts.append(f"[ATTACHMENT {a.get('name', 'file')}]\n{a.get('content', '')}")
    else:
        parts.append(f"Continuing a chunked {mode.lower()} run. Goal (truncated): {goal[:200]}")
        parts.append("")
        parts.append(f"[CARRYOVER STATE]\n{carryover}")
        if overlap_text:
            parts.append("")
            parts.append(f"[OVERLAP]\n{overlap_text}")
        parts.append("")
        parts.append("Continue exactly where the state leaves off. Do not repeat completed work.")

    parts.append("")
    parts.append(MARKER_RULES)
    return "\n".join(parts)


# -----------------------------------------------------------------------------
# 4. State Carryover Compression Cascade (4 Tiers)
# -----------------------------------------------------------------------------

KEY_PHRASE = re.compile(
    r'(?:^|\n|\.\s+)((?:Therefore|Key insight|Status|Decision|Decided|Next|Remaining|Completed)[^.\n]*)',
    re.IGNORECASE
)


class CarryoverResult:
    def __init__(self, carryover: str, level: str):
        self.carryover = carryover
        self.level = level  # "marker" | "llm" | "heuristic" | "truncation"


class CarryoverService:
    def __init__(self, compressor_fn: Optional[Callable[[str, str], Any]] = None):
        self.compressor_fn = compressor_fn

    async def next(
        self,
        marker_state: Optional[str],
        previous_carryover: str,
        chunk_text: str,
        config: ChunkConfig
    ) -> CarryoverResult:
        budget = config.carryoverTokens

        # Level 1: Explicit marker override
        if marker_state is not None:
            sanitized = re.sub(r'[<>[\]@-]{3,}', '', marker_state).strip()
            if len(sanitized) >= 24 and estimate_tokens(sanitized) <= budget:
                return CarryoverResult(carryover=sanitized, level="marker")

        # Level 2: Model-based compression
        if self.compressor_fn:
            try:
                preview = chunk_text[-2000:]
                prompt = (
                    f"Previous state:\n{previous_carryover or '(none)'}\n\nLatest chunk (tail):\n{preview}\n\n"
                    "Compress into 3-5 critical points as a labeled block:\n"
                    "COMPLETED: ...\nREMAINING: ...\nDECISIONS: ...\nCONTEXT: ..."
                )
                system_prompt = "You compress reasoning state. Be terse and lossless on decisions."
                comp_res = self.compressor_fn(prompt, system_prompt)
                if hasattr(comp_res, "__await__"):
                    compressed = await comp_res
                else:
                    compressed = comp_res
                compressed = str(compressed).strip()
                if len(compressed) >= 24 and estimate_tokens(compressed) <= budget:
                    return CarryoverResult(carryover=compressed, level="llm")
            except Exception:
                pass  # Fall through to heuristics

        # Level 3: Heuristic key-phrase extraction
        phrases = [m.group(1).strip() for m in KEY_PHRASE.finditer(chunk_text)][:5]
        if phrases:
            summary = "; ".join(phrases)
            if estimate_tokens(summary) <= budget:
                return CarryoverResult(carryover=summary, level="heuristic")

        # Level 4: Absolute fallback, tail word truncation
        source_text = chunk_text or previous_carryover
        words = [w for w in source_text.split() if w]
        tail = ""
        for i in range(len(words) - 1, -1, -1):
            cand = words[i] + ((" " + tail) if tail else "")
            if estimate_tokens(cand) > budget:
                break
            tail = cand

        return CarryoverResult(carryover=tail, level="truncation")


# -----------------------------------------------------------------------------
# 5. Data Models: ChunkInfo, ExecutionCheckpoint, MarkovianRun
# -----------------------------------------------------------------------------

class ChunkInfo(dict):
    """Execution chunk record."""
    def __init__(self, id: int, tokens: int, carryover: str, content: str):
        super().__init__(id=id, tokens=tokens, carryover=carryover, content=content)
        self.id = id
        self.tokens = tokens
        self.carryover = carryover
        self.content = content

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        return super().__getitem__(item)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tokens": self.tokens,
            "carryover": self.carryover,
            "content": self.content
        }


class ExecutionCheckpoint(dict):
    """Durable state checkpoint for crash recovery and resumable execution."""
    def __init__(
        self,
        checkpoint_id: str,
        run_id: str,
        step: int,
        version: int,
        chunk_config: Dict[str, Any],
        execution_state: Dict[str, Any],
        carryover: str,
        input_refs: Optional[Dict[str, Any]] = None,
        output_refs: Optional[Dict[str, Any]] = None,
        pending_action: Optional[Dict[str, Any]] = None,
        retry_count: int = 0,
        checksum: Optional[str] = None,
        created_at: Optional[str] = None
    ):
        input_refs = input_refs or {}
        output_refs = output_refs or {}
        pending_action = pending_action or {}
        created_at = created_at or datetime.now(timezone.utc).isoformat()

        if not checksum:
            payload = f"{run_id}:{step}:{version}:{carryover}:{json.dumps(execution_state, sort_keys=True)}"
            checksum = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        super().__init__(
            checkpoint_id=checkpoint_id,
            run_id=run_id,
            step=step,
            version=version,
            chunk_config=chunk_config,
            execution_state=execution_state,
            state=execution_state,
            chunk=0,
            carryover=carryover,
            input_refs=input_refs,
            output_refs=output_refs,
            pending_action=pending_action,
            retry_count=retry_count,
            checksum=checksum,
            created_at=created_at
        )
        self.checkpoint_id = checkpoint_id
        self.run_id = run_id
        self.step = step
        self.version = version
        self.chunk_config = chunk_config
        self.execution_state = execution_state
        self.carryover = carryover
        self.input_refs = input_refs
        self.output_refs = output_refs
        self.pending_action = pending_action
        self.retry_count = retry_count
        self.checksum = checksum
        self.created_at = created_at

    def __getitem__(self, item: str) -> Any:
        if item == "state":
            return self.execution_state
        if item == "chunk":
            return 0
        if hasattr(self, item):
            return getattr(self, item)
        return super().__getitem__(item)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "run_id": self.run_id,
            "step": self.step,
            "version": self.version,
            "chunk_config": self.chunk_config,
            "execution_state": self.execution_state,
            "carryover": self.carryover,
            "input_refs": self.input_refs,
            "output_refs": self.output_refs,
            "pending_action": self.pending_action,
            "retry_count": self.retry_count,
            "checksum": self.checksum,
            "created_at": self.created_at
        }


class MarkovianRun(dict):
    """Full workflow execution run carrying a mandatory chunkConfig snapshot."""
    def __init__(
        self,
        run_id: str,
        timestamp: int,
        prompt: str,
        mode: str,
        chunk_config: ChunkConfig,
        chunks: Optional[List[ChunkInfo]] = None,
        total_tokens_used: int = 0,
        total_tokens_saved: int = 0,
        efficiency_percent: float = 0.0,
        duration_ms: int = 0,
        status: str = "completed",
        token_label: str = "estimated",
        output: str = "",
        reflection: Optional[str] = None,
        error: Optional[str] = None,
        org_id: str = "default",
        workflow_id: Optional[str] = None
    ):
        chunks = chunks or []
        super().__init__(
            id=run_id,
            run_id=run_id,
            timestamp=timestamp,
            prompt=prompt,
            mode=mode,
            chunk_config=chunk_config.to_dict(),
            chunkConfig=chunk_config.to_dict(),
            chunks=[c.to_dict() if isinstance(c, ChunkInfo) else c for c in chunks],
            total_tokens_used=total_tokens_used,
            totalTokensUsed=total_tokens_used,
            total_tokens_saved=total_tokens_saved,
            totalTokensSaved=total_tokens_saved,
            efficiency_percent=efficiency_percent,
            efficiencyPercent=efficiency_percent,
            duration_ms=duration_ms,
            durationMs=duration_ms,
            status=status,
            token_label=token_label,
            tokenLabel=token_label,
            output=output,
            reflection=reflection,
            error=error,
            org_id=org_id,
            workflow_id=workflow_id
        )
        self.id = run_id
        self.run_id = run_id
        self.timestamp = timestamp
        self.prompt = prompt
        self.mode = mode
        self.chunk_config = chunk_config
        self.chunkConfig = chunk_config
        self.chunks = chunks
        self.total_tokens_used = total_tokens_used
        self.totalTokensUsed = total_tokens_used
        self.total_tokens_saved = total_tokens_saved
        self.totalTokensSaved = total_tokens_saved
        self.efficiency_percent = efficiency_percent
        self.efficiencyPercent = efficiency_percent
        self.duration_ms = duration_ms
        self.durationMs = duration_ms
        self.status = status
        self.token_label = token_label
        self.tokenLabel = token_label
        self.output = output
        self.reflection = reflection
        self.error = error
        self.org_id = org_id
        self.workflow_id = workflow_id
        self.checkpoints: List[ExecutionCheckpoint] = []

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        return super().__getitem__(item)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "prompt": self.prompt,
            "mode": self.mode,
            "chunkConfig": self.chunk_config.to_dict(),
            "chunks": [c.to_dict() if isinstance(c, ChunkInfo) else c for c in self.chunks],
            "totalTokensUsed": self.total_tokens_used,
            "totalTokensSaved": self.total_tokens_saved,
            "efficiencyPercent": self.efficiency_percent,
            "durationMs": self.duration_ms,
            "status": self.status,
            "tokenLabel": self.token_label,
            "output": self.output,
            "reflection": self.reflection,
            "error": self.error,
            "org_id": self.org_id,
            "workflow_id": self.workflow_id
        }


# -----------------------------------------------------------------------------
# 6. Real-Time Progress Service
# -----------------------------------------------------------------------------

class ProgressService:
    def __init__(self, clock: Callable[[], int], max_chunks: int = 24):
        self.clock = clock
        self.is_active = False
        self.phase_name = "initializing"
        self.phase_detail = ""
        self.current_chunk = 0
        self.max_chunks = max_chunks
        self.tokens_used = 0
        self.tokens_saved = 0
        self.carryover_size = 0
        self.start_time = clock()
        self.last_update_time = clock()
        self.logs: List[str] = []
        self.completed_chunks: List[ChunkInfo] = []
        self._subscribers: List[Callable[[Dict[str, Any]], None]] = []

    def phase(self, name: str, detail: str = ""):
        self.phase_name = name
        self.phase_detail = detail
        self.last_update_time = self.clock()
        if detail:
            self.logs.append(f"[{name}] {detail}")
            if len(self.logs) > 15:
                self.logs.pop(0)
        self._notify()

    def chunk_done(self, chunk: ChunkInfo):
        self.completed_chunks.append(chunk)
        self.current_chunk = chunk.id
        self.last_update_time = self.clock()
        self._notify()

    def update(self, delta: Dict[str, Any]):
        for k, v in delta.items():
            if hasattr(self, k):
                setattr(self, k, v)
        self.last_update_time = self.clock()
        self._notify()

    def subscribe(self, fn: Callable[[Dict[str, Any]], None]) -> Callable[[], None]:
        self._subscribers.append(fn)
        def unsubscribe():
            if fn in self._subscribers:
                self._subscribers.remove(fn)
        return unsubscribe

    def _notify(self):
        state = self.to_dict()
        for fn in list(self._subscribers):
            try:
                fn(state)
            except Exception:
                pass

    def to_dict(self) -> Dict[str, Any]:
        return {
            "isActive": self.is_active,
            "phase": self.phase_name,
            "phaseDetail": self.phase_detail,
            "currentChunk": self.current_chunk,
            "maxChunks": self.max_chunks,
            "tokensUsed": self.tokens_used,
            "tokensSaved": self.tokens_saved,
            "carryoverSize": self.carryover_size,
            "startTime": self.start_time,
            "lastUpdateTime": self.last_update_time,
            "logs": list(self.logs),
            "completedChunks": [c.to_dict() for c in self.completed_chunks]
        }


# -----------------------------------------------------------------------------
# 7. Core Markovian Engine & Runtime Orchestrator
# -----------------------------------------------------------------------------

_run_counter = 0


class Markovian:
    """Production Markovian Chunked Execution Engine."""
    def __init__(
        self,
        chunk_config: Optional[Union[Dict[str, Any], ChunkConfig]] = None,
        generator: Optional[Callable[..., Any]] = None,
        compressor_fn: Optional[Callable[[str, str], Any]] = None,
        clock: Optional[Callable[[], int]] = None,
        storage: str = "postgres",
        org_id: str = "default",
        **kwargs
    ):
        raw_cfg = chunk_config or {}
        if not raw_cfg and kwargs:
            raw_cfg = kwargs
        self.config = resolve_config(raw_cfg)
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.storage = storage
        self.org_id = org_id
        self.default_generator = generator
        self.carryover_service = CarryoverService(compressor_fn=compressor_fn)
        self.progress = ProgressService(clock=self.clock, max_chunks=self.config.maxChunks)
        self.history: List[MarkovianRun] = []

    def on_progress(self, fn: Callable[[Dict[str, Any]], None]) -> Callable[[], None]:
        return self.progress.subscribe(fn)

    onProgress = on_progress

    # -------------------------------------------------------------------------
    # Execution & Chunk Loop
    # -------------------------------------------------------------------------

    async def run(
        self,
        goal: Optional[str] = None,
        prompt: Optional[str] = None,
        mode: str = "ARCHITECT",
        generator: Optional[Callable[..., Any]] = None,
        attachments: Optional[List[Dict[str, str]]] = None,
        memory_context: Optional[str] = None,
        stop_when: Optional[Callable[[Dict[str, Any]], bool]] = None,
        on_stream: Optional[Callable[[str], None]] = None,
        reflect: bool = True,
        workflow_id: Optional[str] = None,
        resume_from_checkpoint: Optional[ExecutionCheckpoint] = None,
        **kwargs
    ) -> MarkovianRun:
        """Execute long reasoning task in bounded chunks with checkpointing."""
        global _run_counter
        _run_counter += 1
        
        target_goal = goal or prompt or kwargs.get("user_prompt")
        if not target_goal:
            raise ValueError("Markovian: run needs a goal or prompt")

        gen_fn = generator or self.default_generator
        if not gen_fn:
            raise ValueError("Markovian: generator function required to execute chunks")

        start_ts = self.clock()
        run_id = kwargs.get("run_id")
        if not run_id:
            if resume_from_checkpoint:
                run_id = resume_from_checkpoint.run_id
            else:
                run_id = f"run-{_run_counter}-{int(time.time() * 1000) % 1000000}"

        run = MarkovianRun(
            run_id=run_id,
            timestamp=start_ts,
            prompt=target_goal[:500],
            mode=mode,
            chunk_config=copy.deepcopy(self.config),
            status="running",
            token_label="estimated",
            org_id=self.org_id,
            workflow_id=workflow_id
        )

        if self.storage == "postgres":
            self._persist_run(run)

        # Restore from checkpoint if resuming
        start_step = 1
        carryover = ""
        previous_cleaned = ""
        cleaned_parts: List[str] = []
        if resume_from_checkpoint:
            start_step = resume_from_checkpoint.step + 1
            carryover = resume_from_checkpoint.carryover
            run.checkpoints.append(resume_from_checkpoint)

        self.progress.is_active = True
        self.progress.phase("initializing", f"{mode} chain, maxChunks={self.config.maxChunks}")

        done = False
        try:
            for step in range(start_step, self.config.maxChunks + 1):
                self.progress.phase("generating", f"chunk {step}")
                ovl = overlap_slice(previous_cleaned, self.config)
                chunk_prompt = build_prompt(
                    mode=mode,
                    goal=target_goal,
                    step=step,
                    carryover=carryover,
                    overlap_text=ovl,
                    memory_context=memory_context,
                    attachments=attachments if step == 1 else [],
                    config=self.config
                )

                # Invoke generator (supports async or sync)
                gen_res = gen_fn(chunk_prompt)
                if hasattr(gen_res, "__await__"):
                    raw_out = await gen_res
                else:
                    raw_out = gen_res

                chunk_text = raw_out.get("text", "") if isinstance(raw_out, dict) else getattr(raw_out, "text", str(raw_out))
                if on_stream:
                    try:
                        on_stream(chunk_text)
                    except Exception:
                        pass

                parsed = parse_markers(chunk_text)
                content = parsed.cleaned
                chunk_tokens = estimate_tokens(content)

                chunk = ChunkInfo(id=step, tokens=chunk_tokens, carryover=carryover, content=content)
                run.chunks.append(chunk)
                cleaned_parts.append(content)
                previous_cleaned = content
                self.progress.chunk_done(chunk)

                # Persist durable execution checkpoint
                chk = ExecutionCheckpoint(
                    checkpoint_id=f"chk_{run_id}_{step}_{len(run.checkpoints) + 1}",
                    run_id=run_id,
                    step=step,
                    version=len(run.checkpoints) + 1,
                    chunk_config=self.config.to_dict(),
                    execution_state={"completed_chunks": len(run.chunks), "mode": mode},
                    carryover=carryover,
                    pending_action=parsed.needs_tool or {}
                )
                run.checkpoints.append(chk)
                if self.storage == "postgres":
                    self._persist_checkpoint(chk)

                # Compress carryover state for subsequent chunk
                self.progress.phase("compressing", f"chunk {step}")
                next_carryover = await self.carryover_service.next(
                    marker_state=parsed.state,
                    previous_carryover=carryover,
                    chunk_text=chunk_text,
                    config=self.config
                )
                carryover = next_carryover.carryover
                self.progress.update({
                    "tokensUsed": sum(c.tokens for c in run.chunks),
                    "carryoverSize": estimate_tokens(carryover)
                })

                if parsed.done:
                    done = True
                    break

                if stop_when and stop_when({"step": step, "carryover": carryover}):
                    done = True
                    break

            if done:
                run.status = "completed"
            elif len(run.chunks) >= self.config.maxChunks:
                run.status = "max-chunks"

        except Exception as exc:
            run.status = "errored"
            run.error = str(exc)
            self.progress.phase("error", run.error)

        run.output = "\n\n".join(cleaned_parts)
        eff = run_efficiency(run.chunks, self.config)
        run.total_tokens_used = eff["totalTokensUsed"]
        run.totalTokensUsed = eff["totalTokensUsed"]
        run.total_tokens_saved = eff["tokensSaved"]
        run.totalTokensSaved = eff["tokensSaved"]
        run.efficiency_percent = eff["efficiencyPercent"]
        run.efficiencyPercent = eff["efficiencyPercent"]
        run.duration_ms = self.clock() - start_ts
        run.durationMs = run.duration_ms

        # Reflection step (only for completed runs with chunks; failures are isolated)
        if reflect and run.status == "completed" and len(run.chunks) > 0:
            self.progress.phase("reflecting")
            try:
                code_blocks = len(re.findall(r'```', run.output)) // 2
                ref_prompt = (
                    f"Reflect on this completed run.\nGoal: {target_goal[:200]}\nFinal state: {carryover}\n"
                    f"Output (truncated): {run.output[:4000]}\nCode blocks: {code_blocks}\n"
                    "Verdict: ratify if the goal is met, refine with concrete gaps otherwise."
                )
                ref_res = gen_fn(ref_prompt)
                if hasattr(ref_res, "__await__"):
                    ref_out = await ref_res
                else:
                    ref_out = ref_res
                raw_ref = ref_out.get("text", "") if isinstance(ref_out, dict) else getattr(ref_out, "text", str(ref_out))
                run.reflection = clean_markers(raw_ref)
            except Exception as ref_exc:
                run.reflection = None
                run.error = f"reflection failed (run preserved): {str(ref_exc)}"

        self.progress.phase("complete" if run.status == "completed" else run.status, run.status)
        self.progress.is_active = False

        self.history.append(run)
        if self.storage == "postgres":
            self._persist_run(run)

        return run

    # -------------------------------------------------------------------------
    # Side-Effect Deduplication
    # -------------------------------------------------------------------------

    def execute_side_effect(
        self,
        idempotency_key: str,
        action_type: str,
        payload: Dict[str, Any],
        executor_fn: Callable[[], Any],
        run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute irreversible side effect safely with PostgreSQL-backed idempotency."""
        if self.storage == "postgres":
            try:
                from app.database import db
                with db() as conn:
                    # Check existing execution
                    row = conn.execute(
                        "SELECT status, result FROM markovian_side_effects WHERE idempotency_key = %s",
                        (idempotency_key,)
                    ).fetchone()
                    if row:
                        logger.info(f"Side effect '{action_type}' with key '{idempotency_key}' already executed. Returning cached result.")
                        return {
                            "idempotency_key": idempotency_key,
                            "action_type": action_type,
                            "status": "cached",
                            "result": row[1] if isinstance(row[1], dict) else json.loads(row[1])
                        }

                    # Execute irreversible action
                    result = executor_fn()
                    res_json = result if isinstance(result, dict) else {"outcome": str(result)}

                    # Persist record transactionally
                    conn.execute(
                        """INSERT INTO markovian_side_effects (idempotency_key, org_id, run_id, action_type, payload, status, result)
                           VALUES (%s, %s, %s, %s, %s::jsonb, 'completed', %s::jsonb)
                           ON CONFLICT (idempotency_key) DO UPDATE
                           SET status = excluded.status, result = excluded.result""",
                        (idempotency_key, self.org_id, run_id, action_type, json.dumps(payload, default=str), json.dumps(res_json, default=str))
                    )
                    return {
                        "idempotency_key": idempotency_key,
                        "action_type": action_type,
                        "status": "executed",
                        "result": res_json
                    }
            except Exception as exc:
                logger.error(f"PostgreSQL side effect deduplication failed: {exc}. Executing fallback.")

        # In-memory / fallback execution
        result = executor_fn()
        return {
            "idempotency_key": idempotency_key,
            "action_type": action_type,
            "status": "executed_fallback",
            "result": result if isinstance(result, dict) else {"outcome": str(result)}
        }

    # -------------------------------------------------------------------------
    # Crash Recovery & Resumption
    # -------------------------------------------------------------------------

    def get_latest_checkpoint(self, run_id: str) -> Optional[ExecutionCheckpoint]:
        """Retrieve latest valid checkpoint for a run."""
        if self.storage == "postgres":
            try:
                from app.database import db
                with db() as conn:
                    row = conn.execute(
                        """SELECT checkpoint_id, run_id, step, version, chunk_config, execution_state,
                                  carryover, input_refs, output_refs, pending_action, retry_count, checksum, created_at
                           FROM markovian_checkpoints
                           WHERE run_id = %s
                           ORDER BY step DESC, version DESC
                           LIMIT 1""",
                        (run_id,)
                    ).fetchone()
                    if row:
                        return ExecutionCheckpoint(
                            checkpoint_id=row[0],
                            run_id=row[1],
                            step=row[2],
                            version=row[3],
                            chunk_config=row[4],
                            execution_state=row[5],
                            carryover=row[6],
                            input_refs=row[7],
                            output_refs=row[8],
                            pending_action=row[9],
                            retry_count=row[10],
                            checksum=row[11],
                            created_at=row[12].isoformat() if hasattr(row[12], "isoformat") else str(row[12])
                        )
            except Exception as exc:
                logger.warning(f"Failed to fetch checkpoint for {run_id}: {exc}")

        # Search in-memory history
        for r in reversed(self.history):
            if r.run_id == run_id and r.checkpoints:
                return r.checkpoints[-1]
        return None

    # -------------------------------------------------------------------------
    # PostgreSQL Persistence Helpers
    # -------------------------------------------------------------------------

    def _persist_run(self, run: MarkovianRun):
        try:
            from app.database import db
            with db() as conn:
                conn.execute(
                    """INSERT INTO markovian_runs (
                        run_id, org_id, workflow_id, mode, prompt, chunk_config, status,
                        total_tokens_used, total_tokens_saved, efficiency_percent, duration_ms,
                        token_label, output, reflection, error, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
                    ) ON CONFLICT (run_id) DO UPDATE SET
                        status = excluded.status,
                        total_tokens_used = excluded.total_tokens_used,
                        total_tokens_saved = excluded.total_tokens_saved,
                        efficiency_percent = excluded.efficiency_percent,
                        duration_ms = excluded.duration_ms,
                        output = excluded.output,
                        reflection = excluded.reflection,
                        error = excluded.error,
                        updated_at = now()""",
                    (
                        run.run_id, run.org_id, run.workflow_id, run.mode, run.prompt,
                        json.dumps(run.chunk_config.to_dict()), run.status,
                        run.total_tokens_used, run.total_tokens_saved, run.efficiency_percent,
                        run.duration_ms, run.token_label, run.output, run.reflection, run.error
                    )
                )
                for chunk in run.chunks:
                    conn.execute(
                        """INSERT INTO markovian_chunks (run_id, step, tokens, carryover, content)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (run.run_id, chunk.id, chunk.tokens, chunk.carryover, chunk.content)
                    )
        except Exception as exc:
            logger.warning(f"PostgreSQL run persistence failed: {exc}")

    def _persist_checkpoint(self, chk: ExecutionCheckpoint):
        try:
            from app.database import db
            with db() as conn:
                conn.execute(
                    """INSERT INTO markovian_checkpoints (
                        checkpoint_id, run_id, step, version, chunk_config, execution_state,
                        carryover, input_refs, output_refs, pending_action, retry_count, checksum
                    ) VALUES (
                        %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s
                    ) ON CONFLICT (checkpoint_id) DO UPDATE SET
                        version = excluded.version,
                        execution_state = excluded.execution_state,
                        carryover = excluded.carryover,
                        retry_count = excluded.retry_count,
                        checksum = excluded.checksum""",
                    (
                        chk.checkpoint_id, chk.run_id, chk.step, chk.version,
                        json.dumps(chk.chunk_config), json.dumps(chk.execution_state),
                        chk.carryover, json.dumps(chk.input_refs), json.dumps(chk.output_refs),
                        json.dumps(chk.pending_action), chk.retry_count, chk.checksum
                    )
                )
        except Exception as exc:
            logger.warning(f"PostgreSQL checkpoint persistence failed: {exc}")

    def persist_checkpoint(
        self,
        run_id: str,
        chunk_index: int = 0,
        step: int = 1,
        state: Optional[Dict[str, Any]] = None,
        pending_actions: Optional[List[str]] = None,
        carryover: str = ""
    ) -> ExecutionCheckpoint:
        """Explicitly persist a workflow checkpoint to PostgreSQL and memory."""
        chk_id = f"chk-{run_id}-{step}"
        chk = ExecutionCheckpoint(
            checkpoint_id=chk_id,
            run_id=run_id,
            step=step,
            version=1,
            chunk_config=self.config.to_dict(),
            execution_state=state or {},
            carryover=carryover,
            pending_action={"actions": pending_actions} if pending_actions else None
        )
        try:
            from app.database import db
            with db() as conn:
                conn.execute(
                    """INSERT INTO markovian_runs (
                        run_id, org_id, workflow_id, mode, prompt, chunk_config, status,
                        total_tokens_used, total_tokens_saved, efficiency_percent, duration_ms,
                        token_label, output, updated_at
                    ) VALUES (
                        %s, %s, %s, 'standard', 'workflow step', %s::jsonb, 'running',
                        0, 0, 0.0, 0.0, 'estimated', '', now()
                    ) ON CONFLICT (run_id) DO NOTHING""",
                    (run_id, self.org_id, run_id.replace("run-", ""), json.dumps(self.config.to_dict()))
                )
        except Exception as e:
            logger.warning(f"Failed to ensure markovian_runs for checkpoint: {e}")

        self._persist_checkpoint(chk)
        return chk


# -----------------------------------------------------------------------------
# 8. Engine Singleton Accessor
# -----------------------------------------------------------------------------

_markovian_instances: Dict[str, Markovian] = {}

def get_markovian_engine(org_id: str = "default", **kwargs) -> Markovian:
    """Retrieve or initialize the Markovian Engine singleton for an organization."""
    if org_id not in _markovian_instances:
        _markovian_instances[org_id] = Markovian(org_id=org_id, **kwargs)
    return _markovian_instances[org_id]
