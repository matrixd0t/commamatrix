# tests/test_manager.py

"""Tests for Manager, ServiceInstanceManager, ServiceInstanceRegistry."""

from __future__ import annotations

import sys
import types
import weakref

import pytest

from commamatrix.core.classes.manager import (
    Manager,
    ServiceInstanceManager,
    ServiceInstanceRegistry,
)
from commamatrix.core.classes.service import AbstractService, ServiceDescriptor
from commamatrix.core.classes.source import PythonServiceSource
from tests.conftest import stub_agent


class TestServiceInstanceRegistry:
    def test_set_and_get_by_class(self):
        reg = ServiceInstanceRegistry()
        inst = object()
        reg[str] = inst
        assert reg.get(str) is inst

    def test_set_and_get_by_id(self):
        reg = ServiceInstanceRegistry()
        inst = object()
        reg["my_id"] = inst
        assert reg.get_by_id("my_id") is inst

    def test_require_existing(self):
        reg = ServiceInstanceRegistry()
        inst = object()
        reg[str] = inst
        assert reg.require(str) is inst

    def test_require_missing_raises(self):
        reg = ServiceInstanceRegistry()
        with pytest.raises(KeyError, match="Service int not registered"):
            reg.require(int)

    def test_contains_class(self):
        reg = ServiceInstanceRegistry()
        reg[str] = object()
        assert str in reg
        assert int not in reg

    def test_contains_id(self):
        reg = ServiceInstanceRegistry()
        reg["x"] = object()
        assert "x" in reg
        assert "y" not in reg

    def test_remove_by_instance(self):
        reg = ServiceInstanceRegistry()
        inst = object()
        reg[str] = inst
        reg["id1"] = inst
        reg.remove_by_instance(inst)
        assert str not in reg
        assert "id1" not in reg

    def test_get_all(self):
        reg = ServiceInstanceRegistry()
        inst = object()
        reg[str] = inst
        reg["id1"] = inst
        all_insts = reg.get_all(object)
        assert len(all_insts) == 1

    def test_values(self):
        reg = ServiceInstanceRegistry()
        a, b = object(), object()
        reg[str] = a
        reg["x"] = b
        assert reg.values() == {a, b}

    def test_clear(self):
        reg = ServiceInstanceRegistry()
        reg[str] = object()
        reg["x"] = object()
        reg.clear()
        assert str not in reg
        assert "x" not in reg


class TestManagerBasics:
    def test_descriptors_property(self):
        agent = stub_agent()
        mgr = Manager(agent)
        assert list(mgr.descriptors) == []

    def test_mount_and_scan(self):
        agent = stub_agent()
        mgr = Manager(agent)
        src = PythonServiceSource()
        src.set_scope(["nonexistent_module_for_test"])
        mgr.mount(src)
        mgr.scan()
        assert list(mgr.descriptors) == []

    def test_scan_returns_true_on_change(self):
        agent = stub_agent()
        mgr = Manager(agent)
        src = PythonServiceSource()
        src.set_scope(["nonexistent_module_for_test"])
        mgr.mount(src)
        changed = mgr.scan()
        assert changed is True

    def test_scan_returns_false_on_no_change(self):
        agent = stub_agent()
        mgr = Manager(agent)
        src = PythonServiceSource()
        src.set_scope(["nonexistent_module_for_test"])
        mgr.mount(src)
        mgr.scan()
        changed = mgr.scan()
        assert changed is False

    def test_is_current_with_valid_descriptor(self):
        from commamatrix.core.classes.service import Service
        agent = stub_agent()
        mgr = Manager(agent)
        src = PythonServiceSource()
        mod = types.ModuleType("mgr_test_mod")

        class Svc(Service):
            async def start(self): pass
            async def stop(self): pass
        Svc.__module__ = "mgr_test_mod"
        mod.Svc = Svc
        sys.modules["mgr_test_mod"] = mod
        try:
            src.set_scope(["mgr_test_mod"])
            mgr.mount(src)
            mgr.scan()
            desc = next(iter(mgr.descriptors))
            assert mgr.is_current(desc) is True
        finally:
            del sys.modules["mgr_test_mod"]

    def test_is_current_with_stale_descriptor(self):
        agent = stub_agent()
        mgr = Manager(agent)
        src = PythonServiceSource()
        src.set_scope(["nonexistent"])
        mgr.mount(src)
        d = ServiceDescriptor(
            id="stale://x",
            service_cls=AbstractService,
            metadata={},
            _source_ref=weakref.ref(src),
        )
        assert mgr.is_current(d) is False

    def test_on_change_callback(self):
        agent = stub_agent()
        mgr = Manager(agent)
        changed = []
        mgr.on_change = lambda: changed.append(True)
        src = PythonServiceSource()
        src.set_scope(["nonexistent"])
        mgr.mount(src)
        mgr.scan()
        assert changed == [True]

    def test_unmount_removes_source(self):
        agent = stub_agent()
        mgr = Manager(agent)
        src = PythonServiceSource()
        src.set_scope(["nonexistent"])
        mgr.mount(src)
        mgr.scan()
        mgr.unmount(src)
        assert list(mgr.descriptors) == []


class TestServiceInstanceManager:
    @pytest.mark.asyncio
    async def test_creates_and_starts_instances(self):
        from commamatrix.core.classes.service import Service
        class MySvc(Service):
            async def start(self):
                self.started = True
            async def stop(self):
                pass

        mod = types.ModuleType("sim_test_mod")
        mod.MySvc = MySvc
        MySvc.__module__ = "sim_test_mod"
        sys.modules["sim_test_mod"] = mod
        try:
            agent = stub_agent()
            mgr = ServiceInstanceManager(agent)
            mgr.set_scope(["sim_test_mod"])
            await mgr.start()
            instances = mgr.instances
            assert len(instances) == 1
            assert instances[0].__class__ is MySvc
            await mgr.stop()
        finally:
            del sys.modules["sim_test_mod"]

    @pytest.mark.asyncio
    async def test_registry_populated(self):
        from commamatrix.core.classes.service import Service
        class MySvc2(Service):
            async def start(self): pass
            async def stop(self): pass

        mod = types.ModuleType("sim_reg_mod")
        mod.MySvc2 = MySvc2
        MySvc2.__module__ = "sim_reg_mod"
        sys.modules["sim_reg_mod"] = mod
        try:
            agent = stub_agent()
            mgr = ServiceInstanceManager(agent)
            mgr.set_scope(["sim_reg_mod"])
            await mgr.start()
            assert agent.services.get(MySvc2) is not None
            await mgr.stop()
        finally:
            del sys.modules["sim_reg_mod"]
