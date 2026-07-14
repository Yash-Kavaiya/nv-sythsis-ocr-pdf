"""PDF creation: compile the generated .tex with a real LaTeX engine when one
is installed (tectonic / pdflatex / xelatex), otherwise render an equivalent
PDF with the pure-Python fpdf2 renderer. Also rasterizes page 1 to PNG so
vision OCR models can consume the document."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from .fpdf_renderer import render_pdf


def find_latex_engine() -> Optional[list[str]]:
    if shutil.which("tectonic"):
        return ["tectonic", "--keep-logs=false"]
    for engine in ("pdflatex", "xelatex"):
        if shutil.which(engine):
            return [engine, "-interaction=nonstopmode", "-halt-on-error"]
    return None


def compile_tex(tex_source: str, out_pdf: str) -> bool:
    engine = find_latex_engine()
    if not engine:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        tex_file = Path(tmp) / "doc.tex"
        tex_file.write_text(tex_source)
        try:
            subprocess.run(
                engine + [str(tex_file)],
                cwd=tmp, capture_output=True, timeout=90, check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False
        produced = Path(tmp) / "doc.pdf"
        if not produced.exists():
            return False
        shutil.copy(produced, out_pdf)
    return True


def create_pdf(
    tex_source: str,
    doc_type: str,
    record: dict[str, Any],
    currency: str,
    out_pdf: str,
) -> str:
    """Returns the engine that produced the PDF."""
    if compile_tex(tex_source, out_pdf):
        return find_latex_engine()[0]
    render_pdf(doc_type, record, currency, out_pdf)
    return "fpdf2"


def pdf_to_png(pdf_path: str, png_path: str, scale: float = 2.0) -> bool:
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(pdf_path)
        try:
            page = doc[0]
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
            image.save(png_path)
        finally:
            doc.close()
        return True
    except Exception:
        return False
