# core/extensions.py

"""Extension target resolution and per-agent scope management.

Scope entries are module names (str) or directly added declaration objects:
any object stamped with a ``__commamatrix`` marker attribute, such as an
``@instruction`` or ``@tool`` function. Module entries are scanned via their
namespace; declaration entries are owned by definition.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import sys
import types
from collections.abc import Callable, Iterable
from importlib.metadata import packages_distributions
from pathlib import Path
from typing import Literal

ExtensionTarget = str | types.ModuleType
ExtensionOperation = Literal["add", "remove", "reload"]

_MARKER_PREFIX = "__commamatrix"


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


_DISTRIBUTION_ALIASES = {
    # Import names that differ from their PyPI distribution name.
    "PIL": "Pillow",
    "yaml": "PyYAML",
    "cv2": "opencv-python",
    "dotenv": "python-dotenv",
    "dateutil": "python-dateutil",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "bs4": "beautifulsoup4",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "Crypto": "pycryptodome",
    "fitz": "PyMuPDF",
    "win32api": "pywin32",
    "win32com": "pywin32",
    "win32con": "pywin32",
    "pythoncom": "pywin32",
    "pywintypes": "pywin32",
}


def dependency_distribution(import_name: str) -> str:
    """Return the distribution name that likely provides an import name."""
    aliased = _DISTRIBUTION_ALIASES.get(import_name)
    if aliased is not None:
        return aliased
    distributions = packages_distributions().get(import_name)
    return distributions[0] if distributions else import_name


def missing_plugin_dependencies(targets: Iterable[Path | str]) -> list[str]:
    """Return distribution names that plugin targets import but the runtime cannot resolve.

    Imports are collected statically from target sources, so dynamically
    imported modules are not seen. Import names map to distributions via
    installed package metadata and known import-name aliases, falling back to
    the import name itself.
    """
    sources: list[Path] = []
    own_names: set[str] = set()
    for target in targets:
        path = Path(target).expanduser()
        if path.is_dir():
            own_names.add(path.name)
            sources.extend(sorted(path.rglob("*.py")))
        elif path.is_file() and path.suffix.lower() == ".py":
            own_names.add(path.stem)
            sources.append(path)

    missing: set[str] = set()
    for source in sources:
        for name in _source_import_names(source):
            if name in own_names or name in sys.stdlib_module_names:
                continue
            try:
                if importlib.util.find_spec(name) is not None:
                    continue
            except (ImportError, ValueError):
                pass
            missing.add(dependency_distribution(name))
    return sorted(missing)


def _source_import_names(source: Path) -> list[str]:
    """Return top-level import names in a source file; relative imports are skipped."""
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError, UnicodeDecodeError):
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module.split(".")[0])
    return names


class ExtensionRuntimeError(RuntimeError):
    """Raised when an extension target cannot be processed."""


class MissingExtensionDependencyError(ExtensionRuntimeError):
    """Raised when an extension imports a package unavailable to the runtime."""

    def __init__(self, extension_module: str, dependency_module: str) -> None:
        self.extension_module = extension_module
        self.dependency_module = dependency_module
        super().__init__(
            f"Extension '{extension_module}' requires missing dependency "
            f"'{dependency_module}'. Install it with: pip install {dependency_module}"
        )


class ExtensionRuntime:
    """Resolve extension targets and maintain the agent's active scope.

    Scope entries are module names (str) or directly added declaration objects.
    """

    def __init__(self) -> None:
        self._scope: list[object] = []

    @property
    def scope(self) -> tuple[object, ...]:
        return tuple(self._scope)

    @property
    def scope_list(self) -> list[object]:
        return self._scope

    def replace_scope(self, scope: Iterable[object]) -> None:
        self._scope = list(scope)

    def apply(self, targets: Iterable[object], operation: ExtensionOperation) -> list[object]:
        """Apply an extension operation and restore scope when it fails."""
        handlers: dict[ExtensionOperation, Callable[[object], bool]] = {
            "add": self._add,
            "remove": self._remove,
            "reload": self._reload,
        }
        handler = handlers[operation]
        handled: list[object] = []
        original_scope = list(self._scope)

        for entry in targets:
            target: object | None = None
            try:
                target = self.resolve_entry(entry)
                if target is None:
                    continue
                if handler(target):
                    handled.append(target)
            except ExtensionRuntimeError:
                self._scope = original_scope
                raise
            except Exception as exc:
                self._scope = original_scope
                label = target if isinstance(target, str) else repr(entry)
                raise ExtensionRuntimeError(f"Failed to process extension {label}: {exc}") from exc

        return handled

    @staticmethod
    def resolve_entry(target: object) -> object | None:
        """Resolve a target to a scope entry: a module name or the declaration object itself."""
        if isinstance(target, (str, types.ModuleType)):
            return ExtensionRuntime.resolve_module_name(target)
        if ExtensionRuntime._is_declaration(target):
            return target
        return None

    @staticmethod
    def _is_declaration(obj: object) -> bool:
        return any(name.startswith(_MARKER_PREFIX) for name in dir(obj))

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

    @staticmethod
    def _import_extension_module(module_name: str) -> types.ModuleType:
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            missing_name = exc.name
            if (
                    missing_name
                    and missing_name != module_name
                    and not missing_name.startswith(module_name + ".")
            ):
                raise MissingExtensionDependencyError(module_name, missing_name) from exc
            raise

    def _add(self, entry: object) -> bool:
        if isinstance(entry, str):
            return self._add_module(entry)
        if not any(item is entry for item in self._scope):
            self._scope.append(entry)
        return True

    def _add_module(self, module_name: str) -> bool:
        if module_name not in sys.modules:
            self._import_extension_module(module_name)

        prefix = module_name + "."
        active = {item for item in self._scope if isinstance(item, str)}
        new_names: list[str] = []
        for name in [module_name, *sorted(sys.modules)]:
            if (name == module_name or name.startswith(prefix)) and name not in active:
                active.add(name)
                new_names.append(name)
        self._scope.extend(new_names)
        return True

    def _remove(self, entry: object) -> bool:
        if isinstance(entry, str):
            return self._remove_module(entry)
        before = len(self._scope)
        self._scope = [item for item in self._scope if item is not entry]
        return len(self._scope) < before

    def _remove_module(self, module_name: str) -> bool:
        prefix = module_name + "."
        before = len(self._scope)
        self._scope = [
            item
            for item in self._scope
            if not (isinstance(item, str) and (item == module_name or item.startswith(prefix)))
        ]
        return len(self._scope) < before

    def _reload(self, entry: object) -> bool:
        if isinstance(entry, str):
            return self._reload_module(entry)
        # Direct declarations are live objects with nothing to re-import;
        # reload only ensures the declaration is present.
        if not any(item is entry for item in self._scope):
            self._scope.append(entry)
        return True

    def _reload_module(self, module_name: str) -> bool:
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
            self._import_extension_module(module_name)
            alive = sorted(
                name
                for name in sys.modules
                if name == module_name or name.startswith(prefix)
            )
            self._scope = [
                *[
                    item
                    for item in original_scope
                    if not (isinstance(item, str) and (item == module_name or item.startswith(prefix)))
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
