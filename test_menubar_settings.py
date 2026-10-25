from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("AppKit")
pytest.importorskip("rumps")

import fokuskeeper_menubar as mb


@pytest.fixture(autouse=True)
def no_open_settings(tmp_path):
    with patch.object(mb, "_settings_proc", None), \
         patch.object(mb, "MENUBAR_LOG", tmp_path / "menubar.log"):
        yield


def _popen(returncode=None):
    proc = MagicMock(pid=4242)
    proc.poll.return_value = returncode
    return proc


def test_open_settings_uses_bundled_daemon_when_packaged():
    daemon = Path("/App/Contents/MacOS/FokusKeeperDaemon")
    with patch.object(mb, "DAEMON_EXECUTABLE", daemon), \
         patch.object(mb.subprocess, "Popen", return_value=_popen()) as popen:
        mb.open_settings()
    assert popen.call_args.args[0] == [str(daemon), "settings"]


def test_open_settings_uses_script_for_source_install():
    with patch.object(mb, "DAEMON_EXECUTABLE", None), \
         patch.object(mb.subprocess, "Popen", return_value=_popen()) as popen:
        mb.open_settings()
    assert popen.call_args.args[0][1:] == [str(mb.DAEMON_SCRIPT), "settings"]


def test_open_settings_does_not_wait_for_the_window():
    # The menu bar froze while Settings was open because it blocked on
    # subprocess.run; it must only start the process.
    with patch.object(mb.subprocess, "Popen", return_value=_popen()), \
         patch.object(mb.subprocess, "run") as run:
        mb.open_settings()
    run.assert_not_called()


def test_second_click_focuses_open_window_instead_of_opening_another():
    with patch.object(mb.subprocess, "Popen", return_value=_popen()) as popen, \
         patch.object(mb, "_focus_settings_window") as focus:
        mb.open_settings()
        mb.open_settings()
    assert popen.call_count == 1
    focus.assert_called_once_with(4242)


def test_logs_launch_failure():
    with patch.object(mb, "DAEMON_EXECUTABLE", Path("/missing/FokusKeeperDaemon")), \
         patch.object(mb.subprocess, "Popen", side_effect=FileNotFoundError("nope")):
        mb.open_settings()
    assert "Settings could not start" in mb.MENUBAR_LOG.read_text()


def test_reap_logs_error_exit_and_allows_reopening():
    with patch.object(mb.subprocess, "Popen", return_value=_popen(returncode=1)) as popen:
        mb.open_settings()
        mb.reap_settings()
        assert mb._settings_proc is None
        mb.open_settings()
    assert popen.call_count == 2
    assert "Settings exited 1" in mb.MENUBAR_LOG.read_text()
