# tests/test_config.py

"""Tests for ConfigField and Config."""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from commamatrix.components.config import Config, ConfigField, close_agent_logging, get_agent_logger, log_format, log_level


class TestConfigField:
    def test_default_value(self):
        f = ConfigField[int](name="x", default=42)
        assert f.default == 42
        assert f.has_default is True
        assert f.name == "x"

    def test_callable_default(self):
        f = ConfigField[str](name="key", default=lambda: "lazy")
        assert f.default == "lazy"

    def test_no_default(self):
        f = ConfigField[str](name="key")
        assert f.has_default is False
        assert f.default is None

    def test_description(self):
        f = ConfigField[str](name="k", description="test desc")
        assert f.description == "test desc"

    def test_set_name(self):
        class MyService:
            my_field = ConfigField[str](description="test")
        assert MyService.my_field.name == "my_field"

    def test_class_getitem_factory(self):
        field_type = ConfigField[str]
        assert callable(field_type)


class TestConfig:
    def test_get_from_overrides(self):
        f = ConfigField[str](name="key")
        cfg = Config(overrides={f: "value"})
        assert cfg.get(f) == "value"

    def test_get_from_defaults(self):
        f = ConfigField[str](name="key")
        cfg = Config(defaults={f: "default_val"})
        assert cfg.get(f) == "default_val"

    def test_get_from_field_default(self):
        f = ConfigField[int](name="x", default=10)
        cfg = Config()
        assert cfg.get(f) == 10

    def test_overrides_take_precedence(self):
        f = ConfigField[str](name="key", default="field_def")
        cfg = Config(overrides={f: "override"}, defaults={f: "default"})
        assert cfg.get(f) == "override"

    def test_defaults_take_precedence_over_field(self):
        f = ConfigField[str](name="key", default="field_def")
        cfg = Config(defaults={f: "config_default"})
        assert cfg.get(f) == "config_default"

    def test_missing_field_raises(self):
        f = ConfigField[str](name="missing")
        cfg = Config()
        with pytest.raises(RuntimeError, match="Missing configuration field"):
            cfg.get(f)

    def test_set(self):
        f = ConfigField[str](name="key")
        cfg = Config()
        cfg.set(f, "new_val")
        assert cfg.get(f) == "new_val"

    def test_has_override(self):
        f = ConfigField[str](name="key")
        cfg = Config(overrides={f: "val"})
        assert cfg.has_override(f) is True
        cfg2 = Config()
        assert cfg2.has_override(f) is False

    def test_contains(self):
        f_with_default = ConfigField[str](name="k", default="d")
        f_without = ConfigField[str](name="k2")
        cfg = Config()
        assert f_with_default in cfg
        assert f_without not in cfg

    def test_update_defaults(self):
        f = ConfigField[str](name="key")
        cfg = Config()
        cfg.update_defaults({f: "added"})
        assert cfg.get(f) == "added"

    def test_update_defaults_does_not_override_existing(self):
        f = ConfigField[str](name="key")
        cfg = Config(defaults={f: "original"})
        cfg.update_defaults({f: "new"})
        assert cfg.get(f) == "original"

    def test_agent_logger_uses_configured_level_and_format(self, capsys):
        agent = SimpleNamespace(
            name="test-agent",
            config=Config(overrides={log_level: "WARNING", log_format: "%(levelname)s:%(message)s"}),
        )
        logger = get_agent_logger(agent, "config-test")
        logger.info("hidden")
        logger.warning("visible")
        output = capsys.readouterr().err
        close_agent_logging(agent)

        assert "hidden" not in output
        assert "WARNING:visible" in output
