"""Keep the test suite away from the developer's real DevOrch data.

Several modules compute ``Path.home() / ".devorch"`` at import time, and some tests (for example
``Permissions().set_tool_permission(...)``) save through those paths. Without isolation, running
``pytest`` overwrote the developer's real ``~/.devorch/permissions.yaml`` (replacing their saved rules
with ``edit: allow`` / ``filesystem: allow``) and wrote to their real sessions folder.

This must run before the application modules are imported, hence environment variables set at import
time of this conftest rather than a fixture.
"""

import os
import shutil
import tempfile

_TEST_HOME = tempfile.mkdtemp(prefix="devorch-test-home-")

# Path.home() reads HOME on POSIX and USERPROFILE on Windows
os.environ["HOME"] = _TEST_HOME
os.environ["USERPROFILE"] = _TEST_HOME
os.environ.pop("HOMEDRIVE", None)
os.environ.pop("HOMEPATH", None)
# never read from or write to the developer's real keychain
os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
# and no real API keys leak into tests
for _var in (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "OPENROUTER_API_KEY",
    "TOGETHER_API_KEY",
    "GITHUB_TOKEN",
    "DEEPSEEK_API_KEY",
    "MOONSHOT_API_KEY",
    "CUSTOM_API_KEY",
):
    os.environ.pop(_var, None)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TEST_HOME, ignore_errors=True)
