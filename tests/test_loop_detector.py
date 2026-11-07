from core.loop_detector import LoopDetector, LoopSeverity, is_error_result


class TestLoopDetector:
    def test_normal_calls_no_loop(self):
        detector = LoopDetector()
        verdict = detector.check_and_record("search", {"pattern": "*.py"})
        assert verdict.severity == LoopSeverity.NONE
        assert verdict.should_block is False

        verdict2 = detector.check_and_record("filesystem", {"action": "read", "path": "main.py"})
        assert verdict2.severity == LoopSeverity.NONE

    def test_duplicate_warning_and_halt(self):
        detector = LoopDetector(duplicate_warning_threshold=2, duplicate_halt_threshold=3)

        # First call: fine
        v1 = detector.check_and_record("search", {"pattern": "*.py"})
        assert v1.severity == LoopSeverity.NONE

        # Second call: identical -> warning
        v2 = detector.check_and_record("search", {"pattern": "*.py"})
        assert v2.severity == LoopSeverity.WARNING
        assert v2.should_block is False
        assert "exact arguments" in v2.message

        # Third call: identical -> halt
        v3 = detector.check_and_record("search", {"pattern": "*.py"})
        assert v3.severity == LoopSeverity.HALT
        assert v3.should_block is True
        assert "prevent an infinite loop" in v3.message

    def test_error_thrashing(self):
        detector = LoopDetector(error_threshold=3)

        detector.check_and_record(
            "shell", {"command": "invalid1"}, result="Error: command not found"
        )
        detector.check_and_record("shell", {"command": "invalid2"}, result="Error: file not found")
        v3 = detector.check_and_record(
            "shell", {"command": "invalid3"}, result="Error: permission denied"
        )

        assert v3.severity == LoopSeverity.WARNING
        assert "Last 3 tool calls resulted in errors" in v3.message

    def test_oscillation_loop(self):
        detector = LoopDetector()

        detector.check_and_record("filesystem", {"action": "read", "path": "a.txt"})
        detector.check_and_record("filesystem", {"action": "read", "path": "b.txt"})
        detector.check_and_record("filesystem", {"action": "read", "path": "a.txt"})
        v4 = detector.check_and_record("filesystem", {"action": "read", "path": "b.txt"})

        assert v4.severity == LoopSeverity.WARNING
        assert "oscillating loop" in v4.message

    def test_turn_advisory(self):
        detector = LoopDetector()
        assert detector.get_turn_advisory(10, 15) is None
        assert "2 iterations remaining" in detector.get_turn_advisory(13, 15)
        assert "FINAL iteration" in detector.get_turn_advisory(14, 15)


# ── the agent's before/after pattern ────────────────────────────────────────


class TestBeforeAfterRecording:
    """The agent calls check_and_record before a tool runs and record_result after it."""

    @staticmethod
    def run_call(detector, name, args, output="ok"):
        pre = detector.check_and_record(name, args)
        if pre.should_block:
            return pre, None
        return pre, detector.record_result(name, args, output)

    def test_a_single_call_is_counted_once(self):
        d = LoopDetector()
        self.run_call(d, "shell", {"command": "pytest"})
        assert len(d.history) == 1

    def test_first_call_of_anything_gets_no_notice(self):
        d = LoopDetector()
        pre, post = self.run_call(d, "shell", {"command": "pytest"})
        assert pre.severity == LoopSeverity.NONE and post.severity == LoopSeverity.NONE

    def test_different_commands_never_trigger_the_duplicate_warning(self):
        # regression: every call used to get "You have already executed this exact command"
        d = LoopDetector()
        for i in range(8):
            pre, post = self.run_call(d, "shell", {"command": f"echo {i}"})
            assert pre.severity == LoopSeverity.NONE, i
            assert post.severity == LoopSeverity.NONE, i

    def test_second_identical_call_warns_and_third_halts(self):
        d = LoopDetector()
        args = {"command": "pytest"}
        pre1, _ = self.run_call(d, "shell", args)
        pre2, _ = self.run_call(d, "shell", args)
        pre3, _ = self.run_call(d, "shell", args)
        assert pre1.severity == LoopSeverity.NONE
        assert pre2.severity == LoopSeverity.WARNING and not pre2.should_block  # not blocked yet
        assert pre3.severity == LoopSeverity.HALT and pre3.should_block

    def test_the_same_command_after_other_work_is_not_a_repeat(self):
        d = LoopDetector()
        self.run_call(d, "shell", {"command": "pytest"})
        self.run_call(d, "edit", {"path": "a.py"})
        pre, _ = self.run_call(
            d, "shell", {"command": "pytest"}
        )  # run tests, edit, run tests again
        assert pre.severity == LoopSeverity.NONE

    def test_error_streak_survives_the_pre_check(self):
        # regression: the pre-check reset the streak to 0, so 3 failures in a row never fired
        d = LoopDetector(error_threshold=3)
        posts = [
            self.run_call(d, "shell", {"command": f"bad{i}"}, "Error: nope")[1] for i in range(3)
        ]
        assert [p.severity for p in posts] == [
            LoopSeverity.NONE,
            LoopSeverity.NONE,
            LoopSeverity.WARNING,
        ]
        assert "Last 3 tool calls resulted in errors" in posts[2].message

    def test_a_success_resets_the_error_streak(self):
        d = LoopDetector(error_threshold=3)
        self.run_call(d, "shell", {"command": "a"}, "Error: x")
        self.run_call(d, "shell", {"command": "b"}, "Error: x")
        self.run_call(d, "shell", {"command": "c"}, "STDOUT:\nfine")
        _, post = self.run_call(d, "shell", {"command": "d"}, "Error: x")
        assert post.severity == LoopSeverity.NONE and d.consecutive_errors == 1

    def test_record_result_updates_the_record_without_adding_one(self):
        d = LoopDetector()
        d.check_and_record("shell", {"command": "x"})
        d.record_result("shell", {"command": "x"}, "Error: boom")
        assert len(d.history) == 1
        assert d.history[0].is_error and d.history[0].result_preview.startswith("Error: boom")

    def test_the_pre_check_does_not_touch_the_error_streak(self):
        d = LoopDetector()
        d.record_result("shell", {"command": "a"}, "Error: x")
        d.check_and_record("shell", {"command": "b"})
        assert d.consecutive_errors == 1


class TestErrorDetection:
    def test_errors_are_recognised_by_how_the_result_starts(self):
        for text in (
            "Error: command denied",
            "Error executing shell: boom",
            "STDERR:\nbash: pytest: command not found",
            "Search error: bad pattern",
            "Filesystem error: x",
            "  \nError: leading whitespace",
        ):
            assert is_error_result(text), text

    def test_content_that_merely_mentions_an_error_is_not_one(self):
        for text in (
            "[app.py] Lines 1-3 of 3\n1 | raise ValueError\n2 | # error: handled",
            "STDOUT:\nTraceback ...\nError: boom",  # a command's own output is not a tool failure
            "Found 3 result(s)",
            "",
            None,
        ):
            assert not is_error_result(text), text
