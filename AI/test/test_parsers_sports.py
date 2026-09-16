import json

import pytest

from DATA_ENGINE.eda.parsers_sports import _load_monthly_json_dir


def test_load_monthly_json_dir_concatenates_all_months(tmp_path):
    (tmp_path / "kbo_202401.json").write_text(
        json.dumps([{"date": "2024-01-01", "game_id": "a"}]), encoding="utf-8"
    )
    (tmp_path / "kbo_202402.json").write_text(
        json.dumps([{"date": "2024-02-01", "game_id": "b"}]), encoding="utf-8"
    )

    df = _load_monthly_json_dir(tmp_path, "kbo_*.json")

    assert len(df) == 2
    assert set(df["game_id"]) == {"a", "b"}


def test_load_monthly_json_dir_skips_schema_check_files(tmp_path):
    (tmp_path / "kbo_202401.json").write_text(
        json.dumps([{"date": "2024-01-01", "game_id": "a"}]), encoding="utf-8"
    )
    (tmp_path / "_schema_check_202401.json").write_text(json.dumps({"rows": []}), encoding="utf-8")

    df = _load_monthly_json_dir(tmp_path, "*.json")

    assert len(df) == 1


def test_load_monthly_json_dir_raises_when_empty(tmp_path):
    with pytest.raises(FileNotFoundError):
        _load_monthly_json_dir(tmp_path, "kbo_*.json")
