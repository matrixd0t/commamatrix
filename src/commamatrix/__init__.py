# src/commamatrix/__init__.py

from importlib.metadata import version as _distribution_version

__version__ = _distribution_version("commamatrix")

from . import builtin as builtin
from . import components as _components
from . import core as _core
from . import utils as utils
from .core.agent.agent import Agent
from .components import *
from .core import *
from .utils import *

__all__ = list(
    dict.fromkeys(
        [
            "Agent",
            "__version__",
            *_components.__all__,
            *_core.__all__,
            *utils.__all__,
            "builtin",
            "utils",
        ]
    )
)

