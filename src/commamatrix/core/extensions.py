# core/extensions.py

"""Extension target resolution and per-agent module scope management."""

from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Literal


ExtensionTarget = str | types.ModuleType
ExtensionOperation = Literal["add", "remove", "reload"]


def discover_plugin_targets(root: Path) -> list[Path]:
    """Return direct Python files and package directories under a plugin root."""
    if not root.is_dir():
        return []

    targets: list[Path] = []
    if (root / "__init__.py").is_file():
        targets.append(root)

    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        if entry.is_file() and entry.suffix.lower() == ".py":
            if entry.name != "__init__.py":
                targets.append(entry)
        elif entry.is_dir() and (entry / "__init__.py").is_file():
            targets.append(entry)
    return targets


class ExtensionRuntimeError(RuntimeError):
    """Raised when an extension target cannot be processed."""


class ExtensionRuntime:
    """Resolve extension targets and maintain their active module scope."""

    def __init__(self) -> None:
        self._scope: list[str] = []

    @property
    def scope(self) -> tuple[str, ...]:
        return tuple(self._scope)

    @property
    def scope_list(self) -> list[str]:
        return self._scope

    def replace_scope(self, scope: Iterable[str]) -> None:
        self._scope = list(scope)

    def apply(self, targets: Iterable[ExtensionTarget], operation: ExtensionOperation) -> list[str]:
        """Apply an extension operation and restore scope when it fails."""
        handlers: dict[ExtensionOperation, Callable[[str], bool]] = {
            "add": self._add,
            "remove": self._remove,
            "reload": self._reload,
        }
        handler = handlers[operation]
        handled: list[str] = []
        original_scope = list(self._scope)

        for entry in targets:
            module_name: str | None = None
            try:
                module_name = self.resolve_module_name(entry)
                if module_name is None:
                    continue
                if handler(module_name):
                    handled.append(module_name)
            except Exception as exc:
                self._scope = original_scope
                target = module_name or f"<{type(entry).__name__}>"
                raise ExtensionRuntimeError(
                    f"Failed to process extension {target}: {exc}"
                ) from exc

        return handled

    @staticmethod
    def resolve_module_name(target: ExtensionTarget) -> str | None:
        """Resolve an import name or filesystem path to a canonical name."""
        if isinstance(target, str):
            path = Path(target).expanduser()
            looks_like_path = (
                path.exists()
                or path.is_absolute()
                or path.parent != Path(".")
                or path.suffix.lower() == ".py"
            )
            if looks_like_path:
                return _module_name_from_path(path)
            return target
        if isinstance(target, types.ModuleType):
            return target.__name__
        return None

    def _add(self, module_name: str) -> bool:
        if module_name not in sys.modules:
            importlib.import_module(module_name)

        prefix = module_name + "."
        active = set(self._scope)
        new_names: list[str] = []
        for name in [module_name, *sorted(sys.modules)]:
            if (name == module_name or name.startswith(prefix)) and name not in active:
                active.add(name)
                new_names.append(name)
        self._scope.extend(new_names)
        return True

    def _remove(self, module_name: str) -> bool:
        prefix = module_name + "."
        before = len(self._scope)
        self._scope = [
            name
            for name in self._scope
            if name != module_name and not name.startswith(prefix)
        ]
        return len(self._scope) < before

    def _reload(self, module_name: str) -> bool:
        prefix = module_name + "."
        original_scope = list(self._scope)
        module_names = tuple(
            name
            for name in sys.modules
            if name == module_name or name.startswith(prefix)
        )
        saved_modules = {name: sys.modules[name] for name in module_names}

        try:
            for name in module_names:
                sys.modules.pop(name, None)
            importlib.import_module(module_name)
            alive = sorted(
                name
                for name in sys.modules
                if name == module_name or name.startswith(prefix)
            )
            self._scope = [
                *[
                    name
                    for name in original_scope
                    if name != module_name and not name.startswith(prefix)
                ],
                *alive,
            ]
        except Exception:
            for name in tuple(sys.modules):
                if name == module_name or name.startswith(prefix):
                    sys.modules.pop(name, None)
            sys.modules.update(saved_modules)
            self._scope = original_scope
            raise
        return True


def _module_name_from_path(path: Path) -> str:
    """Resolve a Python path to its importable name without synthetic modules."""
    resolved = path.resolve()
    if resolved.is_dir():
        source_path = resolved / "__init__.py"
        module_path = resolved
    elif resolved.is_file() and resolved.suffix.lower() == ".py":
        source_path = resolved
        module_path = (
            resolved.parent
            if resolved.name == "__init__.py"
            else resolved.with_suffix("")
        )
    else:
        raise ImportError(f"Extension path is not a Python module: {path}")

    for module_name, module in tuple(sys.modules.items()):
        module_file = getattr(module, "__file__", None)
        if module_file is not None:
            try:
                if Path(str(module_file)).resolve() == source_path.resolve():
                    return module_name
            except OSError:
                continue

    roots: list[Path] = [Path.cwd()]
    roots.extend(Path(entry or Path.cwd()) for entry in sys.path)
    candidates: list[tuple[int, int, int, str, Path]] = []
    seen_roots: set[Path] = set()
    for index, root in enumerate(roots):
        try:
            root = root.resolve()
        except OSError:
            continue
        if root in seen_roots:
            continue
        seen_roots.add(root)
        try:
            relative = module_path.relative_to(root)
        except ValueError:
            continue
        parts = relative.parts
        if not parts or not all(part.isidentifier() for part in parts):
            continue
        first_loaded = int(parts[0] in sys.modules)
        candidates.append((first_loaded, len(root.parts), -index, ".".join(parts), root))

    if candidates:
        _, _, _, module_name, import_root = max(candidates)
    else:
        package_parts: list[str] = []
        package_dir = resolved.parent if resolved.is_file() else resolved
        while (package_dir / "__init__.py").is_file():
            package_parts.insert(0, package_dir.name)
            package_dir = package_dir.parent
        leaf = (
            []
            if resolved.is_dir() or resolved.name == "__init__.py"
            else [resolved.stem]
        )
        parts = package_parts + leaf
        if not parts or not all(part.isidentifier() for part in parts):
            raise ImportError(f"Cannot derive an importable module name from: {path}")
        module_name = ".".join(parts)
        import_root = package_dir

    existing_roots = {
        str(Path(entry or Path.cwd()).resolve()) for entry in sys.path
    }
    if str(import_root) not in existing_roots:
        sys.path.insert(0, str(import_root))
    return module_name
