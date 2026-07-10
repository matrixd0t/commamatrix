# builtin/cli_connector/context.py

from ...api import DialogOrigin


class CliOrigin(DialogOrigin):
    platform: str = 'cli'
    session_id: str
