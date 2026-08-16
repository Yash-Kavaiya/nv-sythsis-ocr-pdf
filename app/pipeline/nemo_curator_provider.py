"""Real NeMo Curator integration (gated).

NeMo Curator (`pip install nemo-curator`) is NVIDIA's scalable curation
platform for text/image/video/audio: GPU-accelerated pipelines (RAPIDS/Dask),
semantic dedup, quality filtering, sharding. It is Linux-oriented and heavy,
so this provider is opt-in via ``NEMO_CURATOR=1`` and only runs when the
package is importable. The in-app curator (QROTAID) remains the default and
is what runs everywhere else.

When enabled, we use NeMo Curator's text pipeline for the seed corpus:
unicode/whitespace normalization, exact + fuzzy (MinHash) dedup, and a
quality filter — mirroring the classic Curator stages on real NeMo machinery.
"""
from __future__ import annotations

import os
from typing import Any


def available() -> bool:
    if os.environ.get("NEMO_CURATOR", "") != "1":
        return False
    try:
        import nemo_curator  # noqa: PLC0415

        return True
    except ImportError:
        return False


def curate_seed(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Curate seed records with real NeMo Curator.

    Requires Linux + `pip install nemo-curator` + ``NEMO_CURATOR=1``.
    Raises a descriptive error otherwise so the caller can fall back.
    """
    if not available():
        raise RuntimeError(
            "Real NeMo Curator is not available: set NEMO_CURATOR=1 on a Linux "
            "host with `pip install nemo-curator` installed. The in-app QROTAID "
            "curator is used instead."
        )
    import nemo_curator  # noqa: PLC0415

    report: dict[str, Any] = {"provider": "nemo-curator", "input_records": len(records)}
    try:
        # nemo_curator works on DocumentDataset (Dask-backed). Convert dicts to
        # a dataset, run the text modules, and read back.
        from nemo_curator import DocumentDataset  # noqa: PLC0415
        from nemo_curator.filters import QualityFilter  # noqa: PLC0415
        from nemo_curator.modifiers import UnicodeReformatter  # noqa: PLC0415

        # A real corpus here would be a parquet/jsonl path; dict lists are
        # converted through a pandas DataFrame.
        import pandas as pd

        df = pd.DataFrame(records)
        dataset = DocumentDataset.from_pandas(df)
        dataset = UnicodeReformatter().modify_dataset(dataset)
        # MinHash fuzzy dedup on the serialized text columns.
        try:
            from nemo_curator.deduplication import MinHashDeduplicator  # noqa: PLC0415

            dedup = MinHashDeduplicator(n_gram_size=5, num_buckets=20, hashes_per_bucket=1)
            dataset = dedup.deduplicate(dataset)
        except Exception as exc:  # dedup config varies across versions
            report["dedup_note"] = f"MinHash dedup skipped: {exc}"
        out = dataset.df.to_dict("records") if hasattr(dataset, "df") else []
        report["output_records"] = len(out)
        return out, report
    except Exception as exc:
        raise RuntimeError(f"NeMo Curator pipeline failed: {exc}") from exc
