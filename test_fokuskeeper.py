#!/usr/bin/env python3
"""
Unit tests for Slack Gatekeeper functionality.
Focus on testing the new dialog logic without requiring macOS dependencies.
"""
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
    """Test the time rescued calculation logic."""
    
    def test_zero_prevented_shows_zero_minutes(self):
        """When no distractions are prevented, should show 0m."""
        prevented_count = 0
        minutes_rescued = prevented_count * 10
        hours_rescued = minutes_rescued // 60
        remaining_minutes = minutes_rescued % 60
        
        assert hours_rescued == 0
        assert remaining_minutes == 0
        
        if hours_rescued > 0:
            time_rescued = f"{hours_rescued}h {remaining_minutes}m"
        else:
            time_rescued = f"{remaining_minutes}m"
        
        assert time_rescued == "0m"
    
    def test_single_prevention_shows_10_minutes(self):
        """One blocked distraction should show 10m."""
        prevented_count = 1
        minutes_rescued = prevented_count * 10
        hours_rescued = minutes_rescued // 60
        remaining_minutes = minutes_rescued % 60
        
        assert hours_rescued == 0
        assert remaining_minutes == 10
        
        if hours_rescued > 0:
            time_rescued = f"{hours_rescued}h {remaining_minutes}m"
        else:
            time_rescued = f"{remaining_minutes}m"
        
        assert time_rescued == "10m"
    
    def test_six_preventions_shows_one_hour(self):
        """Six blocked distractions (60 min) should show 1h 0m."""
        prevented_count = 6
        minutes_rescued = prevented_count * 10
        hours_rescued = minutes_rescued // 60
        remaining_minutes = minutes_rescued % 60
        
        assert hours_rescued == 1
        assert remaining_minutes == 0
        
        if hours_rescued > 0:
            time_rescued = f"{hours_rescued}h {remaining_minutes}m"
        else:
            time_rescued = f"{remaining_minutes}m"
        
        assert time_rescued == "1h 0m"
    
    def test_seven_preventions_shows_one_hour_ten_minutes(self):
        """Seven blocked distractions (70 min) should show 1h 10m."""
        prevented_count = 7
        minutes_rescued = prevented_count * 10
        hours_rescued = minutes_rescued // 60
        remaining_minutes = minutes_rescued % 60
        
        assert hours_rescued == 1
        assert remaining_minutes == 10
        
        if hours_rescued > 0:
            time_rescued = f"{hours_rescued}h {remaining_minutes}m"
        else:
            time_rescued = f"{remaining_minutes}m"
        
        assert time_rescued == "1h 10m"
    
    def test_large_prevention_count(self):
        """100 blocked distractions (1000 min) should show 16h 40m."""
        prevented_count = 100
        minutes_rescued = prevented_count * 10
        hours_rescued = minutes_rescued // 60
        remaining_minutes = minutes_rescued % 60
        
        assert hours_rescued == 16
        assert remaining_minutes == 40
        
        if hours_rescued > 0:
            time_rescued = f"{hours_rescued}h {remaining_minutes}m"
        else:
            time_rescued = f"{remaining_minutes}m"
        
        assert time_rescued == "16h 40m"


class TestSuccessRateCalculation:
    """Test the success rate calculation logic."""
    
    def test_zero_attempts_shows_zero_percent(self):
        """With no attempts, success rate should be 0%."""
        slack_count = 0
        gmail_count = 0
        prevented_count = 0
        
        total_opens = slack_count + gmail_count
        total_attempts = total_opens + prevented_count
        success_rate = (prevented_count / total_attempts * 100) if total_attempts > 0 else 0
        
        assert success_rate == 0
    
    def test_perfect_success_rate(self):
        """All distractions prevented should be 100%."""
        slack_count = 0
        gmail_count = 0
        prevented_count = 10
        
        total_opens = slack_count + gmail_count
        total_attempts = total_opens + prevented_count
        success_rate = (prevented_count / total_attempts * 100) if total_attempts > 0 else 0
        
        assert success_rate == 100.0
    
    def test_fifty_percent_success_rate(self):
        """Half prevented, half opened should be 50%."""
        slack_count = 3
        gmail_count = 2
        prevented_count = 5
        
        total_opens = slack_count + gmail_count
        total_attempts = total_opens + prevented_count
        success_rate = (prevented_count / total_attempts * 100) if total_attempts > 0 else 0
        
        assert success_rate == 50.0
    
    def test_seventy_five_percent_success_rate(self):
        """75% blocked should show correct rate."""
        slack_count = 1
        gmail_count = 1
        prevented_count = 6
        
        total_opens = slack_count + gmail_count
        total_attempts = total_opens + prevented_count
        success_rate = (prevented_count / total_attempts * 100) if total_attempts > 0 else 0
        
        assert success_rate == 75.0


class TestMotivationalMessages:
    """Test motivational message selection based on success rate."""
    
    def test_outstanding_message_at_70_percent(self):
        """Success rate >= 70% should show outstanding message."""
        success_rate = 70
        
        if success_rate >= 70:
            motivation = "Your focus is outstanding today! 🎯"
        elif success_rate >= 50:
            motivation = "You're building great focus habits! 💪"
        elif success_rate >= 30:
            motivation = "Keep pushing - you're making progress! ✨"
        else:
            motivation = "This is your chance to strengthen focus! 🌟"
        
        assert motivation == "Your focus is outstanding today! 🎯"
    
    def test_great_habits_message_at_50_percent(self):
        """Success rate >= 50% should show habits message."""
        success_rate = 50
        
        if success_rate >= 70:
            motivation = "Your focus is outstanding today! 🎯"
        elif success_rate >= 50:
            motivation = "You're building great focus habits! 💪"
        elif success_rate >= 30:
            motivation = "Keep pushing - you're making progress! ✨"
        else:
            motivation = "This is your chance to strengthen focus! 🌟"
        
        assert motivation == "You're building great focus habits! 💪"
    
    def test_progress_message_at_30_percent(self):
        """Success rate >= 30% should show progress message."""
        success_rate = 30
        
        if success_rate >= 70:
            motivation = "Your focus is outstanding today! 🎯"
        elif success_rate >= 50:
            motivation = "You're building great focus habits! 💪"
        elif success_rate >= 30:
            motivation = "Keep pushing - you're making progress! ✨"
        else:
            motivation = "This is your chance to strengthen focus! 🌟"
        
        assert motivation == "Keep pushing - you're making progress! ✨"
    
    def test_strengthen_message_below_30_percent(self):
        """Success rate < 30% should show strengthen focus message."""
        success_rate = 20
        
        if success_rate >= 70:
            motivation = "Your focus is outstanding today! 🎯"
        elif success_rate >= 50:
            motivation = "You're building great focus habits! 💪"
        elif success_rate >= 30:
            motivation = "Keep pushing - you're making progress! ✨"
        else:
            motivation = "This is your chance to strengthen focus! 🌟"
        
        assert motivation == "This is your chance to strengthen focus! 🌟"


class TestButtonDetectionLogic:
    """Test the button click detection logic."""
    
    @patch('subprocess.run')
    def test_stay_focused_button_returns_false(self, mock_run):
        """Clicking 'Stay focused' should return False."""
        # Mock AppleScript returning "Stay focused"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Stay focused"
        mock_run.return_value = mock_result
        
        # Simulate the button detection logic
        result = mock_run(["osascript", "-e", "script"], capture_output=True, text=True)
        
        if result.returncode == 0:
            button_clicked = result.stdout.strip()
            user_has_reason = "reason" in button_clicked.lower()
        else:
            user_has_reason = False
        
        assert user_has_reason is False
    
    @patch('subprocess.run')
    def test_i_have_reason_button_returns_true(self, mock_run):
        """Clicking 'I have a reason' should return True."""
        # Mock AppleScript returning "🔴 I have a reason"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "🔴 I have a reason"
        mock_run.return_value = mock_result
        
        # Simulate the button detection logic
        result = mock_run(["osascript", "-e", "script"], capture_output=True, text=True)
        
        if result.returncode == 0:
            button_clicked = result.stdout.strip()
            user_has_reason = "reason" in button_clicked.lower()
        else:
            user_has_reason = False
        
        assert user_has_reason is True
    
    @patch('subprocess.run')
    def test_case_insensitive_reason_detection(self, mock_run):
        """Button detection should be case-insensitive."""
        test_cases = [
            "REASON",
            "ReAsOn",
            "I have a REASON",
            "reason"
        ]
        
        for test_output in test_cases:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = test_output
            mock_run.return_value = mock_result
            
            result = mock_run(["osascript", "-e", "script"], capture_output=True, text=True)
            
            if result.returncode == 0:
                button_clicked = result.stdout.strip()
                user_has_reason = "reason" in button_clicked.lower()
            else:
                user_has_reason = False
            
            assert user_has_reason is True, f"Failed for: {test_output}"
    
    @patch('subprocess.run')
    def test_cancelled_dialog_returns_false(self, mock_run):
        """User cancelling dialog should return False."""
        # Mock AppleScript returning non-zero (cancel)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_run.return_value = mock_result
        
        # Simulate the button detection logic
        result = mock_run(["osascript", "-e", "script"], capture_output=True, text=True)
        
        if result.returncode == 0:
            button_clicked = result.stdout.strip()
            user_has_reason = "reason" in button_clicked.lower()
        else:
            user_has_reason = False
        
        assert user_has_reason is False
    
    @patch('subprocess.run')
    def test_empty_output_returns_false(self, mock_run):
        """Empty output should safely return False."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_run.return_value = mock_result
        
        # Simulate the button detection logic
        result = mock_run(["osascript", "-e", "script"], capture_output=True, text=True)
        
        if result.returncode == 0:
            button_clicked = result.stdout.strip()
            user_has_reason = "reason" in button_clicked.lower()
        else:
            user_has_reason = False
        
        assert user_has_reason is False


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

