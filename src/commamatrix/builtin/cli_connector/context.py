# builtin/cli_connector/context.py

from ...components import DialogOrigin


class CliOrigin(DialogOrigin):
    platform: str = 'cli'
    session_id: str
