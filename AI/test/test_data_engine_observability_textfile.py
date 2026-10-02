"""DATA_ENGINE.observability.export_textfile 테스트(표준 라이브러리만)."""

from __future__ import annotations

from pathlib import Path

from DATA_ENGINE.observability import export_textfile as ex


def _render(rc=0, previous=None, labels=None, steps=None, ok=None, now=1000):
    return ex.render("j", rc, 12.5, steps or [], ok or {0}, labels or {}, now, previous)


def test_render_format_help_type_and_labels():
    text = _render(steps=[("archive", 0), ("score", 99)])
    assert "# HELP sumgil_job_last_run_timestamp_seconds" in text
    assert "# TYPE sumgil_job_last_rc gauge" in text
    assert 'sumgil_job_last_run_timestamp_seconds{job="j"} 1000' in text
    assert 'sumgil_job_last_success_timestamp_seconds{job="j"} 1000' in text
    assert 'sumgil_job_last_duration_seconds{job="j"} 12.5' in text
    assert 'sumgil_job_step_last_rc{job="j",step="score"} 99' in text
    assert text.endswith("\n")


def test_label_value_escape():
    text = _render(labels={"k": 'a\\b"c\nd'})
    assert 'k="a\\\\b\\"c\\nd"' in text


def test_failure_preserves_previous_success(tmp_path: Path):
    path = tmp_path / "sumgil_j.prom"
    path.write_text(_render(rc=0, now=500, labels={"env": "x"}), encoding="utf-8")
    prev = ex.read_previous_success(path, {"job": "j", "env": "x"})
    assert prev == 500
    text = _render(rc=1, previous=prev, labels={"env": "x"}, now=900)
    assert 'sumgil_job_last_success_timestamp_seconds{job="j",env="x"} 500' in text
    assert 'sumgil_job_last_run_timestamp_seconds{job="j",env="x"} 900' in text
    # 라벨이 다르면 보존하지 않는다.
    assert ex.read_previous_success(path, {"job": "j", "env": "y"}) is None


def test_failure_without_previous_omits_success(tmp_path: Path):
    assert ex.read_previous_success(tmp_path / "none.prom", {"job": "j"}) is None
    assert "last_success" not in _render(rc=1, previous=None)


def test_ok_rc_set_counts_99_as_success():
    assert "last_success" in _render(rc=99, ok={0, 99})
    assert "last_success" not in _render(rc=99, ok={0})


def test_unset_dir_skips_with_exit_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(ex.ENV_DIR, raising=False)
    monkeypatch.chdir(tmp_path)
    assert ex.main(["--job", "j", "--rc", "0", "--duration", "1"]) == 0
    assert "textfile dir 미설정 - 건너뜀" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_invalid_job_name_exits_2(tmp_path):
    argv = ["--job", "bad-name", "--rc", "0", "--duration", "1", "--dir", str(tmp_path)]
    assert ex.main(argv) == 2
    assert list(tmp_path.iterdir()) == []


def test_missing_dir_warns_and_exits_zero(tmp_path, capsys):
    missing = tmp_path / "nope"
    assert ex.main(["--job", "j", "--rc", "0", "--duration", "1", "--dir", str(missing)]) == 0
    assert "경고" in capsys.readouterr().err


def test_atomic_write_leaves_no_tmp_and_env_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(ex.ENV_DIR, str(tmp_path))
    argv = ["--job", "j", "--rc", "99", "--duration", "2", "--ok-rc", "0", "--ok-rc", "99"]
    argv += ["--step", "a=0"]
    assert ex.main(argv) == 0
    assert ex.main(argv) == 0  # 덮어쓰기
    assert sorted(p.name for p in tmp_path.iterdir()) == ["sumgil_j.prom"]
    body = (tmp_path / "sumgil_j.prom").read_text(encoding="utf-8")
    assert 'sumgil_job_step_last_rc{job="j",step="a"} 0' in body
