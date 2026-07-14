"""Pydantic schemas shared across the API."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


SourceType = Literal["huggingface", "sample", "empty"]
DocType = Literal["invoice", "receipt", "letter", "form"]


class PipelineRequest(BaseModel):
    source_type: SourceType = "empty"
    hf_dataset: Optional[str] = None
    hf_config: Optional[str] = None
    hf_split: str = "train"
    prompt: str = Field(..., min_length=3, description="One prompt driving the whole pipeline")
    num_docs: int = Field(5, ge=1, le=50)
    doc_type: Optional[DocType] = None  # None = let the Data Designer infer from the prompt
    seed: Optional[int] = None


class StageReport(BaseModel):
    stage: str
    detail: dict[str, Any] = {}


class DocArtifact(BaseModel):
    index: int
    json_path: str
    tex_path: str
    pdf_path: str
    png_path: Optional[str] = None
    harness_attempts: int = 1
    pdf_engine: str = "fpdf2"


class RunManifest(BaseModel):
    run_id: str
    created_at: str
    request: PipelineRequest
    schema_: dict[str, Any] = Field(default={}, alias="schema")
    stages: list[StageReport] = []
    docs: list[DocArtifact] = []
    llm_backed: bool = False

    model_config = {"populate_by_name": True}


ModelProvider = Literal[
    "nvidia", "openai", "openrouter", "gemini", "anthropic", "azure", "github", "custom"
]


class ModelConfig(BaseModel):
    base_url: str = Field(
        default="", description="OpenAI-compatible base URL, e.g. https://integrate.api.nvidia.com/v1"
    )
    api_key: str = ""
    model: str = Field(default="", description="Model name, e.g. meta/llama-3.2-90b-vision-instruct")
    max_tokens: int = 2048
    provider: ModelProvider = "custom"




class EvalRequest(BaseModel):
    run_id: str
    mode: Literal["model", "upload"]
    model_config_: Optional[ModelConfig] = Field(default=None, alias="model_config")
    predictions: Optional[dict[str, Any]] = Field(
        default=None,
        description='Upload mode: {"0": {...predicted json...}, "1": {...}} keyed by doc index',
    )
    doc_indices: Optional[list[int]] = None  # None = all docs

    model_config = {"populate_by_name": True, "protected_namespaces": ()}


class DocEval(BaseModel):
    index: int
    field_accuracy: float
    fuzzy_field_accuracy: float
    cer: float
    wer: float
    structure_f1: float
    matched_fields: int
    total_fields: int
    error: Optional[str] = None
    fields: list[dict[str, Any]] = []
    prediction: dict[str, Any] = {}


class EvalResult(BaseModel):
    eval_id: str
    run_id: str
    created_at: str
    mode: str
    model_name: Optional[str] = None
    docs: list[DocEval] = []
    aggregate: dict[str, float] = {}
