"""
XGuard Content Safety Service

A lightweight HTTP service that wraps the XGuard-Reason model
to provide real-time content risk scoring via REST API.

Start:
    python app.py
    # or
    uvicorn server.app:app --host 0.0.0.0 --port 8001
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

log = logging.getLogger("xguard")

# ── Settings ───────────────────────────────────────────────────────

class Settings(BaseSettings):
    model_dir: str = Field("./YuFeng-XGuard-Reason-0.6B", description="Path to the XGuard model")
    device: str = Field("auto", description="Inference device: auto / cuda / cpu")
    listen_host: str = Field("0.0.0.0", description="Bind address")
    listen_port: int = Field(8001, description="Bind port")
    default_risk_threshold: float = Field(0.5, ge=0.0, le=1.0, description="Default risk cutoff")
    top_token_count: int = Field(20, description="Number of top tokens to inspect")

    model_config = {"env_prefix": "XGUARD_", "env_file": ".env"}


settings = Settings()

# ── Risk taxonomy ──────────────────────────────────────────────────

SAFE_LABEL = "sec"

KNOWN_RISK_LABELS = frozenset({
    "pc", "dc", "dw", "pi", "ec", "ac", "def", "ti", "cy",
    "ph", "mh", "se", "sci", "pp", "cs", "acc", "mc", "ha",
    "ps", "ter", "sd", "ext", "fin", "med", "law", "cm", "ma", "md",
    SAFE_LABEL,
})

# ── Model wrapper ──────────────────────────────────────────────────

class _ModelHolder:
    """Lazy-loaded singleton that keeps the tokenizer + model in memory."""

    def __init__(self):
        self._ready = False
        self._tok = None
        self._mdl = None
        self._label_map: dict = {}

    def _ensure_loaded(self):
        if self._ready:
            return
        import torch  # noqa: delayed import
        from transformers import AutoModelForCausalLM, AutoTokenizer

        model_path = str(Path(settings.model_dir).resolve())
        log.info("Loading model: %s", model_path)

        self._tok = AutoTokenizer.from_pretrained(model_path)
        self._mdl = AutoModelForCausalLM.from_pretrained(
            model_path, torch_dtype="auto", device_map=settings.device,
        ).eval()
        self._label_map = self._tok.init_kwargs.get("id2risk", {})
        self._ready = True
        log.info("Model ready on %s", self._mdl.device)

    def predict(self, content: str) -> dict[str, float]:
        """Run a single forward pass and return {label: probability}."""
        import torch

        self._ensure_loaded()

        prompt = self._tok.apply_chat_template(
            [{"role": "user", "content": content}],
            tokenize=False, add_generation_prompt=True,
        )
        inputs = self._tok([prompt], return_tensors="pt").to(self._mdl.device)

        with torch.inference_mode():
            gen = self._mdl.generate(
                **inputs, max_new_tokens=1, do_sample=False,
                output_scores=True, return_dict_in_generate=True,
            )

        probs = gen.scores[0][0].softmax(dim=-1)
        top_vals, top_ids = probs.topk(settings.top_token_count)

        scores: dict[str, float] = {}
        for prob, tok_id in zip(top_vals, top_ids):
            token = self._tok.decode([tok_id.item()]).strip()
            if token in scores:
                continue
            if token in self._label_map or token in KNOWN_RISK_LABELS:
                scores[token] = prob.item()
        return scores


_model = _ModelHolder()

# ── Request / Response schemas ─────────────────────────────────────

class ScanRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Content to scan")
    threshold: float | None = Field(None, ge=0.0, le=1.0, description="Override risk cutoff")


class RiskVerdict(BaseModel):
    safe: bool
    label: str | None = None
    score: float = 0.0
    scores: dict[str, float] = Field(default_factory=dict)


# ── Core logic ─────────────────────────────────────────────────────

def _judge(scores: dict[str, float], cutoff: float) -> RiskVerdict:
    """Determine whether content is safe given per-label probabilities."""
    safe_prob = scores.get(SAFE_LABEL, 0.0)

    worst_label, worst_score = None, 0.0
    for lbl, prob in scores.items():
        if lbl == SAFE_LABEL:
            continue
        if prob > worst_score:
            worst_label, worst_score = lbl, prob

    # Model is confident it's safe
    if safe_prob > worst_score:
        return RiskVerdict(safe=True, scores=scores)

    # Worst risk exceeds cutoff
    if worst_score >= cutoff:
        return RiskVerdict(safe=False, label=worst_label, score=worst_score, scores=scores)

    return RiskVerdict(safe=True, scores=scores)


# ── HTTP layer ─────────────────────────────────────────────────────

@asynccontextmanager
async def _on_startup(app: FastAPI):
    log.info("XGuard service starting")
    yield

app = FastAPI(title="XGuard", version="0.1.0", lifespan=_on_startup)


@app.get("/health")
async def healthcheck():
    return {"status": "ok"}


@app.post("/api/check", response_model=RiskVerdict)
async def scan(body: ScanRequest):
    try:
        scores = _model.predict(body.text)
    except Exception:
        log.exception("Prediction error")
        raise HTTPException(status_code=500, detail="Model inference failed")

    cutoff = body.threshold if body.threshold is not None else settings.default_risk_threshold
    return _judge(scores, cutoff)


if __name__ == "__main__":
    uvicorn.run(app, host=settings.listen_host, port=settings.listen_port)
