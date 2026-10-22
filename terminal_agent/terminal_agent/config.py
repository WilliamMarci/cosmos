import os
from pathlib import Path
import tomllib


def load(path=None):
    path = Path(path) if path else Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'terminal-agent/config.toml'
    data = tomllib.loads(path.read_text()) if path.exists() else {}
    return {'executable': 'opencode', 'inherit_opencode': True, 'model': '',
            'timeout': 120, **data}
