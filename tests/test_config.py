from __future__ import annotations

from pathlib import Path

from quarry import __version__
from quarry.config import Settings, resolve_db_paths


class TestVersion:
    def test_version_is_string(self):
        assert isinstance(__version__, str)

    def test_version_format(self):
        parts = __version__.split(".")
        assert len(parts) == 3
        assert all(part.isdigit() for part in parts)


class TestSettings:
    def test_defaults(self):
        settings = Settings(
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        assert settings.aws_default_region == "us-east-1"
        assert settings.s3_bucket == ""
        assert settings.chunk_max_chars == 1800
        assert settings.chunk_overlap_chars == 200
        assert settings.textract_poll_initial == 5.0
        assert settings.textract_max_wait == 900
        assert isinstance(settings.lancedb_path, Path)
        expected = Path.home() / ".quarry" / "data" / "default" / "registry.db"
        assert settings.registry_path == expected

    def test_override_via_constructor(self):
        settings = Settings(
            aws_access_key_id="key",
            aws_secret_access_key="secret",
            aws_default_region="eu-west-1",
            chunk_max_chars=1000,
        )
        assert settings.aws_default_region == "eu-west-1"
        assert settings.chunk_max_chars == 1000

    def test_override_via_env(self, monkeypatch):
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "env-key")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "env-secret")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-southeast-1")
        settings = Settings()
        assert settings.aws_access_key_id == "env-key"
        assert settings.aws_default_region == "ap-southeast-1"

    def test_default_lancedb_path_under_home(self):
        settings = Settings(
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        home = Path.home()
        expected = home / ".quarry" / "data" / "default" / "lancedb"
        assert settings.lancedb_path == expected

    def test_embedding_model_default(self):
        settings = Settings(
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        assert settings.embedding_model == "Snowflake/snowflake-arctic-embed-m-v1.5"

    def test_quarry_root_default(self):
        settings = Settings(
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        assert settings.quarry_root == Path.home() / ".quarry" / "data"


class TestResolveDbPaths:
    def test_default_uses_default_database(self):
        settings = Settings(
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        resolved = resolve_db_paths(settings)
        assert resolved.lancedb_path == settings.quarry_root / "default" / "lancedb"
        expected = settings.quarry_root / "default" / "registry.db"
        assert resolved.registry_path == expected

    def test_named_database(self):
        settings = Settings(
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        resolved = resolve_db_paths(settings, db_name="work")
        assert resolved.lancedb_path == settings.quarry_root / "work" / "lancedb"
        assert resolved.registry_path == settings.quarry_root / "work" / "registry.db"

    def test_lancedb_path_env_override(self, monkeypatch):
        monkeypatch.setenv("LANCEDB_PATH", "/custom/path")
        settings = Settings(
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        resolved = resolve_db_paths(settings, db_name="work")
        assert resolved.lancedb_path == settings.lancedb_path

    def test_does_not_mutate_original(self):
        settings = Settings(
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        original_path = settings.lancedb_path
        resolve_db_paths(settings, db_name="other")
        assert settings.lancedb_path == original_path
