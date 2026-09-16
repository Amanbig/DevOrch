from core.loop_detector import LoopDetector, LoopSeverity


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

        detector.check_and_record("shell", {"command": "invalid1"}, result="Error: command not found")
        detector.check_and_record("shell", {"command": "invalid2"}, result="Error: file not found")
        v3 = detector.check_and_record("shell", {"command": "invalid3"}, result="Error: permission denied")

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
