# tests/test_descriptor_source.py

"""Tests for Descriptor, Source, PythonSource, PythonServiceSource."""

from __future__ import annotations

import sys
import types
import weakref

import pytest

from commamatrix.core.classes.service import (
    AbstractService,
    ServiceDescriptor,
)
from commamatrix.core.classes.source import (
    PythonServiceSource,
)


class TestDescriptor:
    def test_fingerprint_is_deterministic(self):
        src = PythonServiceSource()
        d1 = ServiceDescriptor(id="s://m/C", service_cls=AbstractService, metadata={}, _source_ref=weakref.ref(src))
        d2 = ServiceDescriptor(id="s://m/C", service_cls=AbstractService, metadata={}, _source_ref=weakref.ref(src))
        assert d1.fingerprint == d2.fingerprint

    def test_different_ids_different_fingerprints(self):
        src = PythonServiceSource()
        d1 = ServiceDescriptor(id="s://a", service_cls=AbstractService, metadata={}, _source_ref=weakref.ref(src))
        d2 = ServiceDescriptor(id="s://b", service_cls=AbstractService, metadata={}, _source_ref=weakref.ref(src))
        assert d1.fingerprint != d2.fingerprint

    def test_descriptor_is_frozen(self):
        src = PythonServiceSource()
        d = ServiceDescriptor(id="s://m/C", service_cls=AbstractService, metadata={}, _source_ref=weakref.ref(src))
        with pytest.raises(AttributeError):
            d.id = "other"


class TestPythonServiceSource:
    def test_scan_finds_service_subclass(self):
        from commamatrix.core.classes.service import Service
        class MySvc(Service):
            async def start(self): pass
            async def stop(self): pass

        mod = types.ModuleType("test_svc_mod")
        mod.MySvc = MySvc
        MySvc.__module__ = "test_svc_mod"
        sys.modules["test_svc_mod"] = mod
        try:
            src = PythonServiceSource()
            src.set_scope(["test_svc_mod"])
            descriptors = src.scan()
            assert len(descriptors) == 1
            assert descriptors[0].service_cls is MySvc
            assert descriptors[0].id.startswith("service://")
        finally:
            del sys.modules["test_svc_mod"]

    def test_scan_skips_abstract(self):
        mod = types.ModuleType("test_svc_mod2")
        mod.AbstractService = AbstractService
        AbstractService.__module__ = "test_svc_mod2"
        sys.modules["test_svc_mod2"] = mod
        try:
            src = PythonServiceSource()
            src.set_scope(["test_svc_mod2"])
            descriptors = src.scan()
            assert len(descriptors) == 0
        finally:
            del sys.modules["test_svc_mod2"]

    def test_scan_skips_re_export(self):
        from commamatrix.core.classes.service import Service
        class ForeignSvc(Service):
            async def start(self): pass
            async def stop(self): pass
        ForeignSvc.__module__ = "other_module"

        mod = types.ModuleType("test_reexport")
        mod.ForeignSvc = ForeignSvc
        sys.modules["test_reexport"] = mod
        try:
            src = PythonServiceSource()
            src.set_scope(["test_reexport"])
            descriptors = src.scan()
            assert len(descriptors) == 0
        finally:
            del sys.modules["test_reexport"]

    def test_scan_empty_scope(self):
        src = PythonServiceSource()
        src.set_scope([])
        assert src.scan() == []

    def test_invalidate_and_restore(self):
        src = PythonServiceSource()
        assert src.available is True
        src.invalidate()
        assert src.available is False
        src.restore()
        assert src.available is True

    def test_invalidation_callback(self):
        src = PythonServiceSource()
        called = []
        src._attach_invalidator(lambda: called.append(True))
        src.invalidate()
        assert called == [True]

    def test_detach_invalidator(self):
        src = PythonServiceSource()
        called = []
        cb = lambda: called.append(True)
        src._attach_invalidator(cb)
        src._detach_invalidator(cb)
        src.invalidate()
        assert called == []
