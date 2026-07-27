"""Tests for the daemon-registry collection resolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from quarry.registrar import Registrar
from tests.conftest import FakeRegistryClient


def test_registers_new_directory() -> None:
    client = FakeRegistryClient()
    name, created = Registrar(client).resolve(Path("/proj"), "")
    assert created is True
    assert name  # a fresh unique name was dispatched
    assert [r.directory for r in client._registered] == ["/proj"]


def test_reuses_covering_same_directory() -> None:
    client = FakeRegistryClient([("proj", Path("/proj"))])
    name, created = Registrar(client).resolve(Path("/proj"), "")
    assert created is False
    assert name == "proj"
    assert client._registered == []


def test_collection_override_is_used() -> None:
    client = FakeRegistryClient()
    name, created = Registrar(client).resolve(Path("/proj"), "custom")
    assert created is True
    assert name == "custom"


def test_child_of_registered_parent_raises() -> None:
    client = FakeRegistryClient([("proj", Path("/proj"))])
    with pytest.raises(ValueError, match="already covered by the registration"):
        Registrar(client).resolve(Path("/proj/src"), "")
