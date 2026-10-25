from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("AppKit")
pytest.importorskip("rumps")

import fokuskeeper_menubar as mb


def test_open_settings_uses_bundled_daemon_when_packaged():
    daemon = Path("/App/Contents/MacOS/FokusKeeperDaemon")
    with patch.object(mb, "DAEMON_EXECUTABLE", daemon), \
         patch.object(mb.subprocess, "run", return_value=MagicMock(returncode=0, stderr="")) as run:
        mb.open_settings()
    assert run.call_args.args[0] == [str(daemon), "settings"]


def test_open_settings_uses_script_for_source_install():
    with patch.object(mb, "DAEMON_EXECUTABLE", None), \
         patch.object(mb.subprocess, "run", return_value=MagicMock(returncode=0, stderr="")) as run:
        mb.open_settings()
    assert run.call_args.args[0][1:] == [str(mb.DAEMON_SCRIPT), "settings"]


def test_open_settings_logs_failure(tmp_path):
    log = tmp_path / "menubar.log"
    with patch.object(mb, "DAEMON_EXECUTABLE", Path("/missing/FokusKeeperDaemon")), \
         patch.object(mb, "MENUBAR_LOG", log), \
         patch.object(mb.subprocess, "run", side_effect=FileNotFoundError("nope")):
        mb.open_settings()
    assert "Settings could not start" in log.read_text()
