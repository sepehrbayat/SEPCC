"""Print the configured SEPCC proxy port (for Windows launchers)."""

from config.settings import get_settings

print(get_settings().port)
