from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


@dataclass(frozen=True)
class StagedParquetFile:
    """Metadata for one local Parquet staging file.

    Attributes:
        path: Local Parquet path.
        content_hash: SHA-256 hash of the written file bytes.
        file_size_bytes: File size in bytes.
        row_count: Number of rows written.
        schema_fingerprint: SHA-256 hash of Parquet column names and physical types.
        partition_key: Stable partition key used in the staging manifest.

    Time Complexity:
        O(1) for construction and field access.
    Space Complexity:
        O(1), excluding referenced strings.
    """

    path: Path
    content_hash: str
    file_size_bytes: int
    row_count: int
    schema_fingerprint: str
    partition_key: str

    def manifest_row(
        self,
        *,
        provider: str,
        dataset_name: str,
        asset: str | None,
        freq: str | None,
        start_date: date | None,
        end_date: date | None,
        fetch_run_id: int | None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, object | None]:
        """Return a row compatible with `staging.parquet_file`.

        Time Complexity:
            O(m), where m is the number of metadata keys.
        Space Complexity:
            O(m), for the JSON metadata string.
        """

        return {
            "provider": provider,
            "dataset_name": dataset_name,
            "asset": asset,
            "freq": freq,
            "source_path": str(self.path),
            "content_hash": self.content_hash,
            "file_size_bytes": self.file_size_bytes,
            "row_count": self.row_count,
            "start_date": start_date,
            "end_date": end_date,
            "partition_key": self.partition_key,
            "schema_fingerprint": self.schema_fingerprint,
            "status": "written",
            "fetch_run_id": fetch_run_id,
            "metadata": json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
        }


def write_staging_parquet(
    frame: pd.DataFrame,
    *,
    root_dir: Path,
    provider: str,
    dataset_name: str,
    asset: str | None,
    freq: str | None,
    start_date: date | None,
    end_date: date | None,
    partition_key: str,
) -> StagedParquetFile:
    """Write one DataFrame to an atomic local Parquet staging file.

    Args:
        frame: DataFrame to write.
        root_dir: Staging root directory.
        provider: Provider name.
        dataset_name: Dataset name.
        asset: Asset class, if any.
        freq: Frequency, if any.
        start_date: Inclusive source date, if known.
        end_date: Inclusive source date, if known.
        partition_key: Stable batch partition key.

    Raises:
        ValueError: If `frame` is empty.

    Time Complexity:
        O(n * c), where n is row count and c is column count, dominated by Parquet serialization.
    Space Complexity:
        O(n * c), depending on pandas and pyarrow serialization buffers.
    """

    if frame.empty:
        raise ValueError("cannot write empty staging parquet")

    output_path = _staging_path(
        root_dir=root_dir,
        provider=provider,
        dataset_name=dataset_name,
        asset=asset,
        freq=freq,
        start_date=start_date,
        end_date=end_date,
        partition_key=partition_key,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
    frame.to_parquet(tmp_path, index=False, compression="zstd")
    tmp_path.replace(output_path)

    return StagedParquetFile(
        path=output_path,
        content_hash=file_sha256(output_path),
        file_size_bytes=output_path.stat().st_size,
        row_count=int(frame.shape[0]),
        schema_fingerprint=parquet_schema_fingerprint(output_path),
        partition_key=partition_key,
    )


def _staging_path(
    *,
    root_dir: Path,
    provider: str,
    dataset_name: str,
    asset: str | None,
    freq: str | None,
    start_date: date | None,
    end_date: date | None,
    partition_key: str,
) -> Path:
    start = start_date.isoformat() if start_date else "open"
    end = end_date.isoformat() if end_date else "open"
    return (
        root_dir.expanduser()
        / _safe_path_part(provider)
        / _safe_path_part(dataset_name)
        / _safe_path_part(asset or "all")
        / _safe_path_part(freq or "na")
        / f"{start}_{end}"
        / f"{_safe_path_part(partition_key)}.parquet"
    )


def _safe_path_part(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.=-]+", "_", value.strip())
    return text.strip("._") or "part"


def file_sha256(path: Path) -> str:
    """Return a SHA-256 hash for a local file.

    Args:
        path: Local file path.

    Time Complexity:
        O(n), where n is file size in bytes.
    Space Complexity:
        O(1), excluding the read buffer.
    """

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parquet_schema_fingerprint(path: Path) -> str:
    """Return a stable fingerprint for a Parquet file schema.

    Args:
        path: Local Parquet file path.

    Time Complexity:
        O(c), where c is the number of Parquet columns.
    Space Complexity:
        O(c), for the schema payload.
    """

    schema = pq.read_schema(path)
    payload = [(field.name, str(field.type), bool(field.nullable)) for field in schema]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
