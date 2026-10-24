from pathlib import Path

from siriconsumer.config import Settings, communication_log_root


def test_data_directory_layout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SIRI_DATA_DIR", str(tmp_path))
    settings = Settings(_env_file=None)
    assert settings.state_dir == tmp_path / "state"
    assert settings.database_path == tmp_path / "state" / "siri.db"
    assert settings.spool_path == tmp_path / "spool"
    assert settings.log_path == tmp_path / "logs"
    assert settings.output_path == tmp_path / "output"
    assert communication_log_root() == tmp_path / "logs"
