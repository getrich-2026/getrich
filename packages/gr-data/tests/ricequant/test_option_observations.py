from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from gr_data.common.paths import RawPaths
from gr_data.raw.ricequant.option_observations import read_option_observation, sha256_file


def archive(tmp_path: Path) -> tuple[RawPaths, Path, str]:
    folder = tmp_path / "ricequant" / "option_contract_property" / "observations" / "sample"
    folder.mkdir(parents=True)
    pd.DataFrame({"order_book_id": ["10002752"], "strike_price": [4.343]}).to_parquet(
        folder / "response.parquet", compression="zstd"
    )
    (folder / "receipt.json").write_text(
        json.dumps(
            {
                "provider": "ricequant",
                "rows": 1,
                "response_sha256": sha256_file(folder / "response.parquet"),
            }
        )
    )
    manifest = folder / "sha256-manifest.json"
    manifest.write_text(
        json.dumps({n: sha256_file(folder / n) for n in ("receipt.json", "response.parquet")})
    )
    return RawPaths(tmp_path), folder, sha256_file(manifest)


def test_immutable_observation_preserves_source_values(tmp_path: Path) -> None:
    paths, folder, digest = archive(tmp_path)
    frame, receipt = read_option_observation(paths, folder, manifest_sha256=digest)
    assert frame["strike_price"].tolist() == [4.343]
    assert receipt["rows"] == 1


@pytest.mark.parametrize("name", ["receipt.json", "response.parquet", "sha256-manifest.json"])
def test_modified_source_artifact_is_rejected(tmp_path: Path, name: str) -> None:
    paths, folder, digest = archive(tmp_path)
    with (folder / name).open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="changed"):
        read_option_observation(paths, folder, manifest_sha256=digest)


def test_observation_outside_raw_root_is_rejected(tmp_path: Path) -> None:
    _, folder, digest = archive(tmp_path)
    with pytest.raises(ValueError, match="outside"):
        read_option_observation(RawPaths(tmp_path / "other"), folder, manifest_sha256=digest)
