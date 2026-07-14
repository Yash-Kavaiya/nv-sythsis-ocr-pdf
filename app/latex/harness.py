"""Agent harness that turns ground-truth JSON into .tex code.

Loop: render template -> validate -> (optional) LLM repair -> safe fallback.
The generated .tex is part of the dataset: it is the structural ground truth
that pairs with the rendered PDF for OCR/structure evaluation.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..pipeline.llm import LLMClient

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_LATEX_RE = re.compile("|".join(re.escape(k) for k in LATEX_SPECIALS))

REPAIR_SYSTEM_PROMPT = """You are a LaTeX repair agent. You receive a broken LaTeX document and a list of \
validation errors. Return ONLY the corrected, complete LaTeX source (no markdown fences, no commentary). \
Preserve all visible text content exactly."""


def latex_escape(value: Any) -> Any:
    if isinstance(value, str):
        return _LATEX_RE.sub(lambda m: LATEX_SPECIALS[m.group(0)], value)
    if isinstance(value, dict):
        return {k: latex_escape(v) for k, v in value.items()}
    if isinstance(value, list):
        return [latex_escape(v) for v in value]
    if isinstance(value, float):
        return f"{value:,.2f}"
    return value


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        block_start_string=r"\BLOCK{",
        block_end_string="}",
        variable_start_string=r"\VAR{",
        variable_end_string="}",
        comment_start_string=r"\#{",
        comment_end_string="}",
        trim_blocks=True,
        autoescape=False,
        undefined=StrictUndefined,
    )


def validate_tex(tex: str) -> list[str]:
    errors = []
    if r"\begin{document}" not in tex or r"\end{document}" not in tex:
        errors.append("missing document environment")
    # Brace balance (ignoring escaped braces).
    stripped = tex.replace(r"\{", "").replace(r"\}", "")
    if stripped.count("{") != stripped.count("}"):
        errors.append(f"unbalanced braces ({stripped.count('{')} open vs {stripped.count('}')} close)")
    if re.search(r"\\VAR\{", tex):
        errors.append("unrendered template variables remain")
    for envname in re.findall(r"\\begin\{(\w+)\}", tex):
        if tex.count(rf"\begin{{{envname}}}") != tex.count(rf"\end{{{envname}}}"):
            errors.append(f"unclosed environment: {envname}")
    return errors


def generate_tex(
    record: dict[str, Any],
    schema: dict[str, Any],
    llm: LLMClient,
    max_attempts: int = 2,
) -> tuple[str, int]:
    """Returns (tex_source, attempts_used)."""
    doc_type = schema["doc_type"]
    context = dict(latex_escape(record))
    context.setdefault("currency", latex_escape(schema.get("currency", "$")))
    # StrictUndefined surfaces missing keys; backfill blanks for optional ones.
    for f in schema["fields"]:
        context.setdefault(f["name"], "")
    if "card_last4" not in context:
        context["card_last4"] = ""

    template = _env().get_template(f"{doc_type}.tex.j2")
    tex = template.render(**context)
    attempts = 1

    errors = validate_tex(tex)
    while errors and attempts < max_attempts and llm.available:
        attempts += 1
        try:
            fixed = llm.chat(
                [
                    {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Errors: {errors}\n\nLaTeX source:\n{tex}"},
                ],
                temperature=0.1,
                max_tokens=4096,
            )
            fixed = re.sub(r"^```(?:latex|tex)?|```$", "", fixed.strip(), flags=re.MULTILINE).strip()
            if not validate_tex(fixed):
                tex = fixed
                break
        except Exception:
            break
        errors = validate_tex(tex)

    return tex, attempts
