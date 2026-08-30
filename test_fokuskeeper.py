#!/usr/bin/env python3
"""
Unit tests for FokusKeeper functionality.
Focus on testing the new dialog logic without requiring macOS dependencies.
"""
import os
import pytest
from unittest.mock import patch, MagicMock
import subprocess
from datetime import datetime, timedelta
import json
import tempfile
from pathlib import Path

# Import the module
import fokuskeeper as sg


class TestTimeRescuedCalculation:
    """format_time_rescued() — production helper, 10 min per blocked distraction."""

    def test_zero_prevented_shows_zero_minutes(self):
        assert sg.format_time_rescued(0) == "0m"

    def test_single_prevention_shows_10_minutes(self):
        assert sg.format_time_rescued(1) == "10m"

    def test_six_preventions_shows_one_hour(self):
        assert sg.format_time_rescued(6) == "1h 0m"

    def test_seven_preventions_shows_one_hour_ten_minutes(self):
        assert sg.format_time_rescued(7) == "1h 10m"

    def test_large_prevention_count(self):
        assert sg.format_time_rescued(100) == "16h 40m"


class TestSuccessRateCalculation:
    """compute_success_rate() — production helper."""

    def test_zero_attempts_shows_zero_percent(self):
        assert sg.compute_success_rate(0, 0) == 0

    def test_perfect_success_rate(self):
        assert sg.compute_success_rate(0, 10) == 100.0

    def test_fifty_percent_success_rate(self):
        assert sg.compute_success_rate(5, 5) == 50.0

    def test_seventy_five_percent_success_rate(self):
        assert sg.compute_success_rate(2, 6) == 75.0


class TestMotivationalMessages:
    """motivation_for() — production helper thresholds at 70/50/30."""

    def test_outstanding_message_at_70_percent(self):
        assert sg.motivation_for(70) == "Your focus is outstanding today! 🎯"

    def test_great_habits_message_at_50_percent(self):
        assert sg.motivation_for(50) == "You're building great focus habits! 💪"

    def test_progress_message_at_30_percent(self):
        assert sg.motivation_for(30) == "Keep pushing - you're making progress! ✨"

    def test_strengthen_message_below_30_percent(self):
        assert sg.motivation_for(20) == "This is your chance to strengthen focus! 🌟"


class TestButtonDetectionLogic:
    """parse_dialog_button() — production helper."""

    def test_stay_focused_button_returns_false(self):
        assert sg.parse_dialog_button(0, "Stay focused") is False

    def test_i_have_reason_button_returns_true(self):
        assert sg.parse_dialog_button(0, "🔴 I have a reason") is True

    def test_case_insensitive_reason_detection(self):
        for stdout in ["REASON", "ReAsOn", "I have a REASON", "reason"]:
            assert sg.parse_dialog_button(0, stdout) is True, f"Failed for: {stdout}"

    def test_cancelled_dialog_returns_false(self):
        assert sg.parse_dialog_button(1, "") is False

    def test_empty_output_returns_false(self):
        assert sg.parse_dialog_button(0, "") is False


class TestStateManagement:
    """Test state loading, saving, and daily resets."""
    
    def setup_method(self):
        """Create temporary state file for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_state_file = Path(self.temp_dir) / "test_state.json"
        
    def teardown_method(self):
        """Clean up temporary files."""
        if self.temp_state_file.exists():
            self.temp_state_file.unlink()
        Path(self.temp_dir).rmdir()
    
    def test_load_nonexistent_state_returns_empty_dict(self):
        """Loading state when file doesn't exist should return empty dict."""
        with patch.object(sg, 'STATE_FILE', self.temp_state_file):
            state = sg.load_state()
            assert state == {}
    
    def test_save_and_load_state(self):
        """State should persist across save/load operations."""
        test_state = {
            "stats_date": "2025-12-19",
            "slack_opens": 5,
            "gmail_opens": 3,
            "distractions_prevented": 10
        }
        
        with patch.object(sg, 'STATE_FILE', self.temp_state_file):
            sg.save_state(test_state)
            loaded_state = sg.load_state()
            
            assert loaded_state == test_state
    
    def test_daily_reset_on_new_day(self):
        """Counters should reset when date changes."""
        # Save state from "yesterday"
        yesterday_state = {
            "stats_date": "2025-12-18",
            "slack_opens": 10,
            "gmail_opens": 8,
            "distractions_prevented": 15
        }
        
        with patch.object(sg, 'STATE_FILE', self.temp_state_file):
            sg.save_state(yesterday_state)
            
            # Get today's count (should be 0 since date differs)
            slack_count = sg.get_daily_count("slack")
            gmail_count = sg.get_daily_count("gmail")
            prevented_count = sg.get_prevented_count()
            
            assert slack_count == 0
            assert gmail_count == 0
            assert prevented_count == 0


class TestCooldownAndQuietPeriod:
    """Regression tests for the sliding-cooldown bug.

    Diagnosed 2026-08-11, fixed 2026-08-20. `{app}_last_active_time` served as
    both the cooldown start and the last-touched marker, and the monitor loop
    refreshed it on every allowed focus — so glancing at Slack once every
    COOLDOWN_MINUTES kept the grant alive indefinitely and it never re-prompted.
    Nothing in this suite covered it, which is why it survived. It does now.
    """

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_state_file = Path(self.temp_dir) / "test_state.json"

    def teardown_method(self):
        if self.temp_state_file.exists():
            self.temp_state_file.unlink()
        Path(self.temp_dir).rmdir()

    def _backdate(self, key, minutes):
        state = sg.load_state()
        state[key] = (datetime.now() - timedelta(minutes=minutes)).isoformat()
        sg.save_state(state)

    def test_grant_starts_cooldown(self):
        with patch.object(sg, 'STATE_FILE', self.temp_state_file), \
             patch.object(sg, 'log'):
            sg.allow_access("slack")
            assert sg.is_in_cooldown("slack") is True

    def test_glancing_does_not_extend_cooldown(self):
        """THE BUG: repeated glances must not push the expiry out."""
        with patch.object(sg, 'STATE_FILE', self.temp_state_file), \
             patch.object(sg, 'log'):
            sg.allow_access("slack")
            self._backdate("slack_granted_at", sg.COOLDOWN_MINUTES + 2)

            for _ in range(5):
                sg.update_last_seen("slack")

            assert sg.is_in_cooldown("slack") is False

    def test_cooldown_still_active_before_expiry(self):
        with patch.object(sg, 'STATE_FILE', self.temp_state_file), \
             patch.object(sg, 'log'):
            sg.allow_access("slack")
            self._backdate("slack_granted_at", max(sg.COOLDOWN_MINUTES - 1, 0))
            sg.update_last_seen("slack")
            assert sg.is_in_cooldown("slack") is True

    def test_no_state_means_no_cooldown(self):
        with patch.object(sg, 'STATE_FILE', self.temp_state_file):
            assert sg.is_in_cooldown("slack") is False

    def test_quiet_period_tracks_real_idleness(self):
        """Splitting the clocks must not break the 60-minute quiet period."""
        with patch.object(sg, 'STATE_FILE', self.temp_state_file), \
             patch.object(sg, 'log'):
            sg.update_last_seen("slack")
            assert sg.is_quiet_period("slack") is False

            self._backdate("slack_last_seen", sg.QUIET_PERIOD_MINUTES + 30)
            assert sg.is_quiet_period("slack") is True

    def test_quiet_period_true_when_never_seen(self):
        with patch.object(sg, 'STATE_FILE', self.temp_state_file):
            assert sg.is_quiet_period("slack") is True

    def test_legacy_state_key_still_honoured(self):
        """An existing state file from before the split must keep working."""
        with patch.object(sg, 'STATE_FILE', self.temp_state_file):
            sg.save_state({
                "slack_last_active_time":
                    (datetime.now() - timedelta(minutes=1)).isoformat()
            })
            assert sg.is_in_cooldown("slack") is True

            sg.save_state({
                "slack_last_active_time":
                    (datetime.now() - timedelta(
                        minutes=sg.QUIET_PERIOD_MINUTES + 10)).isoformat()
            })
            assert sg.is_in_cooldown("slack") is False
            assert sg.is_quiet_period("slack") is True

    def test_corrupt_timestamp_does_not_crash(self):
        """A bad timestamp must degrade, not take the daemon down."""
        with patch.object(sg, 'STATE_FILE', self.temp_state_file):
            sg.save_state({
                "slack_granted_at": "not-a-timestamp",
                "slack_last_seen": None,
            })
            assert sg.is_in_cooldown("slack") is False
            assert sg.is_quiet_period("slack") is True

    def test_slack_and_gmail_clocks_are_independent(self):
        with patch.object(sg, 'STATE_FILE', self.temp_state_file), \
             patch.object(sg, 'log'):
            sg.allow_access("slack")
            assert sg.is_in_cooldown("slack") is True
            assert sg.is_in_cooldown("gmail") is False

            sg.update_last_seen("gmail")
            assert sg.is_quiet_period("gmail") is False
            assert sg.is_in_cooldown("gmail") is False


class TestLegacyFileMigration:
    """migrate_legacy_files() copies legacy state/history to the new paths."""

    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.new_state = self.temp_dir / "fokuskeeper-state.json"
        self.new_history = self.temp_dir / "fokuskeeper-history.json"
        self.legacy_state = self.temp_dir / "slack-gatekeeper-state.json"
        self.legacy_history = self.temp_dir / "slack-gatekeeper-history.json"

    def teardown_method(self):
        for f in self.temp_dir.iterdir():
            f.unlink()
        self.temp_dir.rmdir()

    def _patched(self):
        return [
            patch.object(sg, 'STATE_FILE', self.new_state),
            patch.object(sg, 'HISTORY_FILE', self.new_history),
            patch.object(sg, 'LEGACY_STATE_FILE', self.legacy_state),
            patch.object(sg, 'LEGACY_HISTORY_FILE', self.legacy_history),
            patch.object(sg, 'log'),
        ]

    def _migrate(self):
        patches = self._patched()
        for p in patches:
            p.start()
        try:
            sg.migrate_legacy_files()
        finally:
            for p in patches:
                p.stop()

    def test_migration_copies_legacy_files(self):
        self.legacy_state.write_text('{"slack_opens": 4}')
        self.legacy_history.write_text('[{"type": "opened"}]')

        self._migrate()

        assert self.new_state.read_text() == '{"slack_opens": 4}'
        assert self.new_history.read_text() == '[{"type": "opened"}]'
        # Legacy files stay in place as rollback
        assert self.legacy_state.exists()
        assert self.legacy_history.exists()
        # New files are user-only
        assert (self.new_state.stat().st_mode & 0o777) == 0o600
        assert (self.new_history.stat().st_mode & 0o777) == 0o600

    def test_migration_noop_when_new_files_exist(self):
        self.legacy_state.write_text('{"old": true}')
        self.legacy_history.write_text('[{"old": true}]')
        self.new_state.write_text('{"new": true}')
        self.new_history.write_text('[{"new": true}]')

        self._migrate()

        assert self.new_state.read_text() == '{"new": true}'
        assert self.new_history.read_text() == '[{"new": true}]'

    def test_migration_noop_when_legacy_absent(self):
        self._migrate()

        assert not self.new_state.exists()
        assert not self.new_history.exists()


class _TempCliMixin:
    """Temp-file patching for tests that drive main() end to end."""

    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.state_file = self.temp_dir / "state.json"
        self.history_file = self.temp_dir / "history.json"
        self.legacy_state = self.temp_dir / "legacy-state.json"
        self.legacy_history = self.temp_dir / "legacy-history.json"
        self.log_file = self.temp_dir / "logs" / "fokuskeeper.log"

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def _run_main(self, argv):
        with patch.object(sg, 'STATE_FILE', self.state_file), \
             patch.object(sg, 'HISTORY_FILE', self.history_file), \
             patch.object(sg, 'LEGACY_STATE_FILE', self.legacy_state), \
             patch.object(sg, 'LEGACY_HISTORY_FILE', self.legacy_history), \
             patch.object(sg, 'LOG_FILE', self.log_file):
            sg.main(argv)


class TestStatsCommand(_TempCliMixin):
    """`fokuskeeper stats` reads state directly, keyed off {key}_granted_at."""

    def test_stats_with_no_state_file_reports_zeros(self, capsys):
        self._run_main(["stats"])
        out = capsys.readouterr().out

        assert "FokusKeeper" in out
        assert "Slack" in out
        assert "Gmail" in out
        assert "Total opens: 0" in out
        assert "Total blocked: 0" in out

    def test_cooldown_remaining_derives_from_granted_at(self):
        granted = (datetime.now() - timedelta(minutes=1)).isoformat()
        state = {"slack_granted_at": granted}
        with patch.object(sg, 'COOLDOWN_MINUTES', 3):
            remaining = sg.cooldown_remaining_minutes(state, "slack")
        assert 1.8 <= remaining <= 2.0

    def test_stats_shows_cooldown_from_granted_at(self, capsys):
        granted = (datetime.now() - timedelta(minutes=1)).isoformat()
        self.state_file.write_text(json.dumps({
            "stats_date": sg.get_today_date(),
            "slack_opens": 2,
            "slack_prevented": 1,
            "slack_granted_at": granted,
        }))
        with patch.object(sg, 'COOLDOWN_MINUTES', 3):
            self._run_main(["stats"])
        out = capsys.readouterr().out

        assert "2m" in out  # ~2 minutes of cooldown left
        assert "Total opens: 2" in out



class _TempStateMixin:
    """Shared temp-file patching for target/gate/counter tests."""

    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.state_file = self.temp_dir / "state.json"
        self.history_file = self.temp_dir / "history.json"

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def _patches(self):
        return [
            patch.object(sg, 'STATE_FILE', self.state_file),
            patch.object(sg, 'HISTORY_FILE', self.history_file),
            patch.object(sg, 'log'),
        ]


class TestTargetConfig:
    """The ten-target config and the enabled-set seam."""

    def test_enabled_targets_returns_all_ten(self):
        # Point CONFIG_FILE at a nonexistent path so the machine's real
        # config can't leak into the test (absent config = all enabled).
        with patch.object(sg, 'CONFIG_FILE',
                          Path(tempfile.gettempdir()) / "fk-no-such-config.json"):
            targets = sg.enabled_targets()
        assert len(targets) == 10
        assert tuple(t.key for t in targets) == sg.TARGET_KEYS

    def test_slack_and_gmail_keys_unchanged(self):
        assert "slack" in sg.TARGET_KEYS
        assert "gmail" in sg.TARGET_KEYS
        assert sg.TARGET_LABELS["slack"] == "Slack"
        assert sg.TARGET_LABELS["gmail"] == "Gmail"


class _HermeticConfigMixin:
    """Point CONFIG_FILE at a nonexistent path for every test in the class.

    match_app_name/match_url resolve enabled_targets() from CONFIG_FILE when
    called without an explicit targets arg. Without this patch they would read
    the machine's REAL ~/.fokuskeeper-config.json, and the suite would break on
    any machine whose config disables a target. Absent config = all enabled.
    """

    @pytest.fixture(autouse=True)
    def _isolate_config(self):
        temp_dir = Path(tempfile.mkdtemp())
        with patch.object(sg, 'CONFIG_FILE', temp_dir / "no-such-config.json"):
            yield
        temp_dir.rmdir()


class TestAppMatching(_HermeticConfigMixin):
    """Frontmost-app matching is exact on app_name."""

    def test_whatsapp_exact_name_matches(self):
        target = sg.match_app_name("WhatsApp")
        assert target is not None
        assert target.key == "whatsapp"

    def test_lowercase_name_does_not_match(self):
        assert sg.match_app_name("whatsapp") is None

    def test_web_only_target_has_no_app_match(self):
        assert sg.match_app_name("Gmail") is None

    def test_none_and_empty_do_not_match(self):
        assert sg.match_app_name(None) is None
        assert sg.match_app_name("") is None


class TestUrlMatching(_HermeticConfigMixin):
    """URL matching is hostname-suffix, not substring."""

    CASES = [
        ("https://web.whatsapp.com/", "whatsapp"),
        ("https://app.slack.com/client/T1/C1", "slack"),
        ("https://slack.com/intl/en-gb/", None),
        ("https://old.reddit.com/r/x", "reddit"),
        ("https://notreddit.com", None),
        ("https://twitter.com/home", "x"),
        ("https://x.com/home", "x"),
        ("https://mail.google.com/mail/u/0", "gmail"),
    ]

    def test_hostname_suffix_matching(self):
        for url, expected_key in self.CASES:
            target = sg.match_url(url)
            got = target.key if target is not None else None
            assert got == expected_key, f"{url}: expected {expected_key}, got {got}"

    def test_empty_and_garbage_urls_do_not_match(self):
        assert sg.match_url("") is None
        assert sg.match_url("about:blank") is None
        assert sg.match_url("not a url") is None


class TestGatePrecedence(_TempStateMixin):
    """evaluate_gate(): COOLDOWN > FIRST_OPEN > QUIET > PROMPT."""

    def _gate(self, state):
        patches = self._patches()
        for p in patches:
            p.start()
        try:
            sg.save_state(state)
            return sg.evaluate_gate(sg.TARGETS_BY_KEY["slack"])
        finally:
            for p in patches:
                p.stop()

    def test_cooldown_beats_first_open_and_quiet(self):
        # opens == 0 (would be FIRST_OPEN) and never seen (would be QUIET),
        # but an active grant wins.
        gate = self._gate({"slack_granted_at": datetime.now().isoformat()})
        assert gate is sg.Gate.COOLDOWN

    def test_first_open_beats_quiet(self):
        # No cooldown, never seen (quiet would be True) — first open wins.
        gate = self._gate({})
        assert gate is sg.Gate.FIRST_OPEN

    def test_quiet_beats_prompt(self):
        gate = self._gate({
            "stats_date": sg.get_today_date(),
            "slack_opens": 3,
            "slack_last_seen": (datetime.now() - timedelta(
                minutes=sg.QUIET_PERIOD_MINUTES + 5)).isoformat(),
        })
        assert gate is sg.Gate.QUIET

    def test_prompt_when_no_auto_allow_applies(self):
        gate = self._gate({
            "stats_date": sg.get_today_date(),
            "slack_opens": 3,
            "slack_last_seen": datetime.now().isoformat(),
        })
        assert gate is sg.Gate.PROMPT


class TestCounterIndependence(_TempStateMixin):
    """Per-target counters must not bleed into each other."""

    def test_whatsapp_increment_leaves_slack_and_gmail_untouched(self):
        patches = self._patches()
        for p in patches:
            p.start()
        try:
            count = sg.increment_daily_count("whatsapp")
            assert count == 1
            assert sg.get_daily_count("whatsapp") == 1
            assert sg.get_daily_count("slack") == 0
            assert sg.get_daily_count("gmail") == 0
            assert sg.get_prevented_count("whatsapp") == 0
        finally:
            for p in patches:
                p.stop()

    def test_daily_reset_zeroes_all_targets_and_legacy_totals(self):
        patches = self._patches()
        for p in patches:
            p.start()
        try:
            stale = {"stats_date": "2020-01-01",
                     "daily_opens": 40, "distractions_prevented": 41}
            for key in sg.TARGET_KEYS:
                stale[f"{key}_opens"] = 7
                stale[f"{key}_prevented"] = 3
            sg.save_state(stale)

            sg.increment_daily_count("tiktok")  # triggers the new-day reset

            state = sg.load_state()
            assert state["stats_date"] == sg.get_today_date()
            for key in sg.TARGET_KEYS:
                expected = 1 if key == "tiktok" else 0
                assert state[f"{key}_opens"] == expected, key
                assert state[f"{key}_prevented"] == 0, key
            assert state["daily_opens"] == 1
            assert state["distractions_prevented"] == 0
        finally:
            for p in patches:
                p.stop()


class TestDialogMessage(_TempStateMixin):
    """build_dialog_message(): intercepted target + totals, injection-safe."""

    def _stats(self, **overrides):
        stats = [{"key": t.key, "label": t.label, "opens": 0, "prevented": 0}
                 for t in sg.TARGETS]
        for s in stats:
            if s["key"] in overrides:
                s["opens"], s["prevented"] = overrides[s["key"]]
        return stats

    def test_message_contains_target_label_and_totals(self):
        stats = self._stats(whatsapp=(2, 1), slack=(3, 4))
        message = sg.build_dialog_message(stats, sg.TARGETS_BY_KEY["whatsapp"])
        assert "WhatsApp" in message
        assert "2" in message   # target opens
        assert "5" in message   # total opens (2 + 3)
        assert "50m" in message  # 5 prevented * 10 min
        # Motivation line for rate 50% (5 prevented / 10 attempts)
        assert "You're building great focus habits" in message

    def test_message_not_one_line_per_target(self):
        stats = self._stats()
        message = sg.build_dialog_message(stats, sg.TARGETS_BY_KEY["slack"])
        for label in ("TikTok", "LinkedIn", "Reddit"):
            assert label not in message

    def test_hostile_label_is_neutralized(self):
        hostile = sg.Target("evil", 'Slack" & (do shell script "true") & "',
                            None, ())
        stats = self._stats()
        stats.append({"key": "evil", "label": hostile.label,
                      "opens": 1, "prevented": 1})
        message = sg.build_dialog_message(stats, hostile)
        # No raw (unescaped) double quote may survive into the osascript payload.
        assert '"' not in message.replace('\\"', '')
        # The hostile quotes must appear only in escaped form.
        assert '\\" & (do shell script \\"true\\") & \\"' in message


class TestWebSurfaceInjection(_TempStateMixin):
    """WebSurface.restore() must sanitize the URL before interpolation."""

    def test_hostile_url_is_escaped_in_osascript_body(self):
        hostile_url = 'https://app.slack.com/x" & (do shell script "true") & "'
        target = sg.TARGETS_BY_KEY["slack"]
        surface = sg.WebSurface(target, 123, 456, hostile_url)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ok"
        with patch.object(sg.subprocess, 'run', return_value=mock_result) as mock_run, \
             patch.object(sg, 'log'):
            surface.restore()

        assert mock_run.called
        script = mock_run.call_args[0][0][2]
        assert '\\" & (do shell script \\"true\\") & \\"' in script
        assert '"https://app.slack.com/x" & (do shell script' not in script


class TestChromeTabRefValidation:
    """Tab ids come only from get_chrome_front_tab_ref, which requires digits."""

    def _ref_for(self, stdout, returncode=0):
        mock_result = MagicMock()
        mock_result.returncode = returncode
        mock_result.stdout = stdout
        with patch.object(sg.subprocess, 'run', return_value=mock_result):
            return sg.get_chrome_front_tab_ref()

    def test_valid_ids_parse(self):
        assert self._ref_for("12|34\n") == (12, 34)

    def test_non_numeric_ids_rejected(self):
        assert self._ref_for("12|abc") == (None, None)
        assert self._ref_for("abc|12") == (None, None)
        assert self._ref_for('12" & x|34') == (None, None)

    def test_malformed_output_rejected(self):
        assert self._ref_for("") == (None, None)
        assert self._ref_for("12|34|56") == (None, None)
        assert self._ref_for("err: no window", returncode=1) == (None, None)


class TestCliAllTargets(_TempCliMixin):
    """CLI stats iterates every configured target."""

    def test_legacy_shared_prevented_falls_back_to_slack_only(self):
        # Regression: the shared legacy total must not be repeated for every
        # target lacking its own {key}_prevented — that multiplied it by ten.
        state = {
            "stats_date": sg.get_today_date(),
            "whatsapp_prevented": 2,
            "distractions_prevented": 20,
        }
        counters = sg._today_counters(state)
        assert counters["slack"] == (0, 20)      # legacy events were Slack-only
        assert counters["whatsapp"] == (0, 2)    # own key wins
        assert counters["reddit"] == (0, 0)      # no fallback for the rest
        total_prevented = sum(p for _, p in counters.values())
        assert total_prevented == 22

    def test_stats_lists_all_ten_targets(self, capsys):
        self._run_main(["stats"])
        out = capsys.readouterr().out
        for target in sg.TARGETS:
            assert target.label in out, target.label
        assert "Total opens: 0" in out


class _TempConfigMixin:
    """Temp CONFIG_FILE patching for the target-config tests."""

    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.config_file = self.temp_dir / "config.json"

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def _patches(self):
        return [
            patch.object(sg, 'CONFIG_FILE', self.config_file),
            patch.object(sg, 'log'),
        ]


class TestEnabledTargetsConfig(_TempConfigMixin):
    """enabled_targets() reads CONFIG_FILE, defaulting to all targets."""

    def _enabled_keys(self):
        patches = self._patches()
        for p in patches:
            p.start()
        try:
            return tuple(t.key for t in sg.enabled_targets())
        finally:
            for p in patches:
                p.stop()

    def test_absent_config_returns_all_ten(self):
        assert self._enabled_keys() == sg.TARGET_KEYS

    def test_subset_config_returns_those_in_targets_order(self):
        self.config_file.write_text(json.dumps({"enabled": ["reddit", "slack"]}))
        # slack precedes reddit in TARGETS, regardless of config order
        assert self._enabled_keys() == ("slack", "reddit")

    def test_unknown_keys_silently_ignored(self):
        self.config_file.write_text(json.dumps({"enabled": ["reddit", "myspace"]}))
        assert self._enabled_keys() == ("reddit",)

    def test_corrupt_json_returns_all_ten(self):
        self.config_file.write_text("{not json!!")
        assert self._enabled_keys() == sg.TARGET_KEYS

    def test_wrong_shape_returns_all_ten(self):
        for payload in ('{"enabled": "reddit"}', '["reddit", "slack"]',
                        '{"enabled": []}', '"reddit"'):
            self.config_file.write_text(payload)
            assert self._enabled_keys() == sg.TARGET_KEYS, payload

    def test_mtime_based_reload_picks_up_config_changes(self):
        import os as _os
        patches = self._patches()
        for p in patches:
            p.start()
        try:
            self.config_file.write_text(json.dumps({"enabled": ["reddit"]}))
            assert tuple(t.key for t in sg.enabled_targets()) == ("reddit",)

            self.config_file.write_text(json.dumps({"enabled": ["tiktok"]}))
            # Force a visibly newer mtime so the reload is deterministic.
            stat = self.config_file.stat()
            _os.utime(self.config_file,
                      ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
            assert tuple(t.key for t in sg.enabled_targets()) == ("tiktok",)
        finally:
            for p in patches:
                p.stop()

    def test_gating_respects_enabled_set(self):
        self.config_file.write_text(json.dumps({"enabled": ["reddit"]}))
        patches = self._patches()
        for p in patches:
            p.start()
        try:
            assert sg.match_url("https://app.slack.com/client/x") is None
            target = sg.match_url("https://old.reddit.com/r/x")
            assert target is not None and target.key == "reddit"
            assert sg.match_app_name("Slack") is None
        finally:
            for p in patches:
                p.stop()


class TestRunSetup(_TempConfigMixin):
    """run_setup(): native chooser, cancel-safe, writes CONFIG_FILE 0o600."""

    def _run_setup(self, stdout, returncode=0):
        mock_result = MagicMock()
        mock_result.returncode = returncode
        mock_result.stdout = stdout
        patches = self._patches()
        for p in patches:
            p.start()
        try:
            with patch.object(sg.subprocess, 'run',
                              return_value=mock_result) as mock_run:
                sg.run_setup()
            return mock_run
        finally:
            for p in patches:
                p.stop()

    def test_selection_writes_config_in_targets_order(self):
        self._run_setup("Reddit, Slack\n")
        assert json.loads(self.config_file.read_text()) == \
            {"enabled": ["slack", "reddit"]}
        assert (self.config_file.stat().st_mode & 0o777) == 0o600

    def test_cancel_leaves_config_absent(self):
        self._run_setup("false\n")
        assert not self.config_file.exists()

    def test_cancel_leaves_existing_config_untouched(self):
        self.config_file.write_text(json.dumps({"enabled": ["gmail"]}))
        self._run_setup("false\n")
        assert json.loads(self.config_file.read_text()) == {"enabled": ["gmail"]}

    def test_osascript_failure_treated_as_cancel(self):
        self._run_setup("", returncode=1)
        assert not self.config_file.exists()

    def test_chooser_script_lists_all_labels_multi_select(self):
        mock_run = self._run_setup("false\n")
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "osascript"
        script = cmd[2]
        for target in sg.TARGETS:
            assert target.label in script, target.label
        assert "with multiple selections allowed" in script
        assert "default items" in script


class _RecordingSurface:
    """Stub surface that records block/restore/discard calls in order."""

    def __init__(self):
        self.calls = []

    def block(self):
        self.calls.append("block")

    def restore(self):
        self.calls.append("restore")

    def discard(self):
        self.calls.append("discard")


class TestHandleIntercept(_TempStateMixin):
    """handle_intercept(): gate-to-action orchestration, all five branches."""

    def setup_method(self):
        super().setup_method()
        self.surface = _RecordingSurface()
        self.target = sg.TARGETS_BY_KEY["slack"]

    def _intercept(self, seed_state=None, dialog=None):
        """Run handle_intercept hermetically; returns (allowed, mock_dialog)."""
        patches = self._patches() + [
            patch.object(sg, 'CONFIG_FILE', self.temp_dir / "no-config.json"),
            patch.object(sg.time, 'sleep'),  # skip the 0.3s block settle
        ]
        for p in patches:
            p.start()
        try:
            if seed_state is not None:
                sg.save_state(seed_state)
            with patch.object(sg, 'show_confirmation_dialog',
                              return_value=dialog) as mock_dialog:
                allowed = sg.handle_intercept(self.target, self.surface)
            return allowed, mock_dialog
        finally:
            for p in patches:
                p.stop()

    def _state(self):
        return json.loads(self.state_file.read_text())

    @staticmethod
    def _recent(iso_value):
        return (datetime.now()
                - datetime.fromisoformat(iso_value)).total_seconds() < 5

    def _prompt_seed(self):
        """opens>0, recent last_seen, expired (absent) cooldown → Gate.PROMPT."""
        return {
            "stats_date": sg.get_today_date(),
            "slack_opens": 2,
            "slack_last_seen": (datetime.now()
                                - timedelta(minutes=1)).isoformat(),
        }

    def test_cooldown_allows_silently_and_refreshes_last_seen(self):
        seed = {"slack_granted_at": datetime.now().isoformat()}
        allowed, mock_dialog = self._intercept(seed)

        assert allowed is True
        assert mock_dialog.called is False
        assert self.surface.calls == []          # no block
        state = self._state()
        assert state.get("slack_opens", 0) == 0  # not counted
        assert "slack_granted_at" in state       # cooldown clock untouched
        assert self._recent(state["slack_last_seen"])  # glance recorded

    def test_first_open_auto_allows_counts_and_grants_cooldown(self):
        allowed, mock_dialog = self._intercept()  # zero opens today

        assert allowed is True
        assert mock_dialog.called is False
        assert self.surface.calls == []
        state = self._state()
        assert state["slack_opens"] == 1
        assert self._recent(state["slack_granted_at"])  # cooldown granted

    def test_quiet_period_auto_allows_counts_and_grants_cooldown(self):
        seed = {
            "stats_date": sg.get_today_date(),
            "slack_opens": 2,
            "slack_last_seen": (datetime.now() - timedelta(
                minutes=sg.QUIET_PERIOD_MINUTES + 5)).isoformat(),
        }
        allowed, mock_dialog = self._intercept(seed)

        assert allowed is True
        assert mock_dialog.called is False
        assert self.surface.calls == []
        state = self._state()
        assert state["slack_opens"] == 3
        assert self._recent(state["slack_granted_at"])

    def test_prompt_allow_blocks_then_restores(self):
        allowed, mock_dialog = self._intercept(self._prompt_seed(), dialog=True)

        assert allowed is True
        assert mock_dialog.call_count == 1
        assert self.surface.calls == ["block", "restore"]
        state = self._state()
        assert state["slack_opens"] == 3
        assert state.get("slack_prevented", 0) == 0
        assert self._recent(state["slack_granted_at"])

    def test_prompt_deny_blocks_then_discards(self):
        allowed, mock_dialog = self._intercept(self._prompt_seed(), dialog=False)

        assert allowed is False
        assert mock_dialog.call_count == 1
        assert self.surface.calls == ["block", "discard"]
        state = self._state()
        assert state["slack_opens"] == 2                  # not counted
        assert state["slack_prevented"] == 1
        assert "slack_granted_at" not in state            # no cooldown granted


class TestRefreshLastSeen(_TempStateMixin):
    """refresh_last_seen(): only the 15s staleness throttle gates the write.

    Regression for the cooldown-predicate removal: continuous use past the
    cooldown must still count as activity, or a long session reads as a
    quiet period and the next open auto-allows.
    """

    def test_stale_last_seen_refreshes_even_after_cooldown_expired(self):
        patches = self._patches()
        for p in patches:
            p.start()
        try:
            sg.save_state({
                "slack_granted_at": (datetime.now() - timedelta(
                    minutes=sg.COOLDOWN_MINUTES + 5)).isoformat(),
                "slack_last_seen": (datetime.now() - timedelta(
                    seconds=sg.LAST_SEEN_REFRESH_SECONDS + 10)).isoformat(),
            })
            assert sg.is_in_cooldown("slack") is False  # cooldown expired

            sg.refresh_last_seen("slack")

            last_seen = datetime.fromisoformat(
                sg.load_state()["slack_last_seen"])
            assert (datetime.now() - last_seen).total_seconds() < 5
        finally:
            for p in patches:
                p.stop()

    def test_fresh_last_seen_is_not_rewritten(self):
        patches = self._patches()
        for p in patches:
            p.start()
        try:
            fresh = (datetime.now() - timedelta(seconds=5)).isoformat()
            sg.save_state({"slack_last_seen": fresh})

            sg.refresh_last_seen("slack")

            assert sg.load_state()["slack_last_seen"] == fresh  # no write
        finally:
            for p in patches:
                p.stop()


class TestWriteJsonFileAtomic:
    """_write_json_file(): atomic replace, no tmp residue, 0o600 from creation."""

    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_write_leaves_no_tmp_sets_mode_and_parses(self):
        path = self.temp_dir / "state.json"
        sg._write_json_file(path, {"slack_opens": 3})

        assert json.loads(path.read_text()) == {"slack_opens": 3}
        assert (path.stat().st_mode & 0o777) == 0o600
        leftovers = [p.name for p in self.temp_dir.iterdir()
                     if p.name.endswith(".tmp")]
        assert leftovers == []

    def test_overwrite_is_atomic_too(self):
        path = self.temp_dir / "state.json"
        sg._write_json_file(path, {"v": 1})
        sg._write_json_file(path, {"v": 2})

        assert json.loads(path.read_text()) == {"v": 2}
        assert (path.stat().st_mode & 0o777) == 0o600
        assert [p.name for p in self.temp_dir.iterdir()] == ["state.json"]


class TestLoadStateCorrupt(_TempStateMixin):
    """load_state(): a corrupt state file degrades to {} instead of raising."""

    def test_corrupt_json_returns_empty_dict(self):
        patches = self._patches()
        for p in patches:
            p.start()
        try:
            self.state_file.write_text("{not json!!")
            assert sg.load_state() == {}
        finally:
            for p in patches:
                p.stop()


class TestCmdRunDoubleStartGuard:
    """cmd_run(): refuses to start when another daemon pid matches the pattern."""

    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.config_file = self.temp_dir / "config.json"

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def _cmd_run(self, pgrep_stdout):
        fake = subprocess.CompletedProcess(
            ["pgrep", "-f", sg.DAEMON_PROCESS_PATTERN],
            returncode=0 if pgrep_stdout.strip() else 1,
            stdout=pgrep_stdout, stderr="")
        with patch.object(sg, '_run', return_value=fake), \
             patch.object(sg, 'monitor') as mock_monitor, \
             patch.object(sg, 'run_setup') as mock_setup, \
             patch.object(sg, 'CONFIG_FILE', self.config_file), \
             patch.object(sg, 'log'):
            sg.cmd_run()
        return mock_monitor, mock_setup

    def test_foreign_pid_refuses_to_start(self, capsys):
        # A pid that is neither this process nor its parent.
        foreign = str(os.getpid() + 100000)
        mock_monitor, _ = self._cmd_run(f"{foreign}\n{os.getpid()}\n")

        assert mock_monitor.called is False
        assert "already running" in capsys.readouterr().out

    def test_own_and_parent_pids_are_discarded(self):
        # pgrep sees this test process and its parent — not a foreign daemon.
        self.config_file.write_text(json.dumps({"enabled": ["slack"]}))
        mock_monitor, mock_setup = self._cmd_run(
            f"{os.getpid()}\n{os.getppid()}\n")

        assert mock_monitor.called is True
        assert mock_setup.called is False  # config exists, no chooser

    def test_missing_config_still_goes_straight_to_monitor(self):
        # cmd_run() must never show UI itself, even with no config at all —
        # a blocking chooser inside the backgrounded/nohup'd daemon process
        # is what caused a real "daemon never starts, log stays empty"
        # failure on a fresh account. First-run setup is install.sh's job,
        # run in the foreground before the daemon ever starts.
        assert not self.config_file.exists()
        mock_monitor, mock_setup = self._cmd_run(f"{os.getpid()}\n")

        assert mock_monitor.called is True
        assert mock_setup.called is False


class TestRunTimeout:
    """_run(): a TimeoutExpired becomes the returncode-1 failure sentinel."""

    def test_timeout_returns_failure_sentinel(self):
        def raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=["osascript", "-e"], timeout=10)

        with patch.object(sg.subprocess, 'run', side_effect=raise_timeout), \
             patch.object(sg, 'log') as mock_log:
            result = sg._run(["osascript", "-e", "beep"])

        assert result.returncode == 1
        assert result.stdout == ""
        assert mock_log.called  # the timeout is logged, not swallowed


class TestAccessWarnings:
    """Automation-permission failures must be visible, not silent — the
    original whole-feature-dead-with-no-trace bug class, first found on
    Chrome tab reading and generalized here to every osascript call site
    that can hit the same TCC wall on a fresh account.
    """

    def setup_method(self):
        sg._access_warned.clear()

    def _denied(self, stderr="Not authorized to send Apple events."):
        return subprocess.CompletedProcess([], returncode=1, stdout="", stderr=stderr)

    def test_frontmost_app_denied_warns_once_and_returns_none(self):
        with patch.object(sg, '_run', return_value=self._denied()), \
             patch.object(sg, 'log') as mock_log:
            assert sg.get_frontmost_app() is None
            assert sg.get_frontmost_app() is None  # second failure: no repeat warning

        warnings = [c for c in mock_log.call_args_list if "WARNING" in c.args[0]]
        assert len(warnings) == 1
        assert "frontmost" in warnings[0].args[0].lower()

    def test_frontmost_app_success_is_silent(self):
        ok = subprocess.CompletedProcess([], returncode=0, stdout="Slack\n", stderr="")
        with patch.object(sg, '_run', return_value=ok), patch.object(sg, 'log') as mock_log:
            assert sg.get_frontmost_app() == "Slack"
        assert mock_log.called is False

    def test_chrome_tabs_denied_warns_once(self):
        with patch.object(sg, '_run', return_value=self._denied()), \
             patch.object(sg, 'log') as mock_log:
            assert sg.get_chrome_active_tab_url() == ""
            assert sg.get_chrome_active_tab_url() == ""

        warnings = [c for c in mock_log.call_args_list if "WARNING" in c.args[0]]
        assert len(warnings) == 1
        assert "chrome" in warnings[0].args[0].lower()

    def test_quit_app_denied_does_not_claim_success(self):
        with patch.object(sg, '_run', return_value=self._denied()), \
             patch.object(sg, 'log') as mock_log:
            result = sg.quit_app("Slack")

        assert result is False
        logged = [c.args[0] for c in mock_log.call_args_list]
        assert not any(msg == "Quit Slack" for msg in logged)
        assert any("WARNING" in msg and "Slack" in msg for msg in logged)

    def test_quit_app_success_logs_plainly(self):
        ok = subprocess.CompletedProcess([], returncode=0, stdout="", stderr="")
        with patch.object(sg, '_run', return_value=ok), patch.object(sg, 'log') as mock_log:
            result = sg.quit_app("Slack")

        assert result is True
        mock_log.assert_called_once_with("Quit Slack")

    def test_independent_grants_warn_independently(self):
        # Denying System Events must not suppress a later, distinct warning
        # about a specific app's Automation grant (or vice versa) -- these
        # are separate permissions in System Settings.
        with patch.object(sg, '_run', return_value=self._denied()), \
             patch.object(sg, 'log') as mock_log:
            sg.get_frontmost_app()
            sg.quit_app("Slack")
            sg.quit_app("WhatsApp")

        warnings = [c.args[0] for c in mock_log.call_args_list if "WARNING" in c.args[0]]
        assert len(warnings) == 3  # frontmost, quit:Slack, quit:WhatsApp each fire once


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

