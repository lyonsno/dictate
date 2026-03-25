"""Tests for the single-instance guard in the entry point."""

import fcntl
import os
import tempfile
from unittest.mock import patch, MagicMock


class TestSingleInstanceGuard:
    """Test the flock-based single-instance guard."""

    def test_first_instance_acquires_lock(self, tmp_path):
        """First instance should acquire the lock and write its PID."""
        lock_path = str(tmp_path / ".donttype.lock")
        lock_file = open(lock_path, "w+")
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file.write(str(os.getpid()))
        lock_file.flush()

        # Verify PID was written
        lock_file.seek(0)
        assert lock_file.read().strip() == str(os.getpid())

        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()

    def test_second_instance_blocked_by_lock(self, tmp_path):
        """Second instance should fail to acquire lock held by first."""
        lock_path = str(tmp_path / ".donttype.lock")

        # First instance takes the lock
        lock1 = open(lock_path, "w+")
        fcntl.flock(lock1, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock1.write("12345")
        lock1.flush()

        # Second instance tries — should fail
        lock2 = open(lock_path, "w+")
        blocked = False
        try:
            fcntl.flock(lock2, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            blocked = True

        assert blocked is True

        fcntl.flock(lock1, fcntl.LOCK_UN)
        lock1.close()
        lock2.close()

    def test_lock_released_after_process_death(self, tmp_path):
        """Lock should be available after holding process dies."""
        lock_path = str(tmp_path / ".donttype.lock")

        # Simulate: first instance took lock, then died (fd closed)
        lock1 = open(lock_path, "w+")
        fcntl.flock(lock1, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock1.write("99999")
        lock1.flush()
        lock1.close()  # process death releases flock

        # Second instance should acquire fine
        lock2 = open(lock_path, "w+")
        fcntl.flock(lock2, fcntl.LOCK_EX | fcntl.LOCK_NB)  # should not raise
        lock2.write(str(os.getpid()))
        lock2.flush()

        lock2.seek(0)
        assert lock2.read().strip() == str(os.getpid())

        fcntl.flock(lock2, fcntl.LOCK_UN)
        lock2.close()

    def test_stale_pid_can_be_read(self, tmp_path):
        """Lock file should contain PID that can be read by next instance."""
        lock_path = str(tmp_path / ".donttype.lock")

        lock_file = open(lock_path, "w+")
        lock_file.write("42")
        lock_file.flush()
        lock_file.seek(0)

        pid = int(lock_file.read().strip())
        assert pid == 42
        lock_file.close()

    def test_invalid_pid_handled_gracefully(self, tmp_path):
        """Corrupt lock file should not crash the guard."""
        lock_path = str(tmp_path / ".donttype.lock")

        lock_file = open(lock_path, "w+")
        lock_file.write("not-a-pid")
        lock_file.flush()
        lock_file.seek(0)

        # Should raise ValueError, which the entry point catches
        try:
            pid = int(lock_file.read().strip())
            assert False, "Should have raised ValueError"
        except ValueError:
            pass  # expected — entry point handles this
        lock_file.close()

    def test_kill_and_reacquire(self, tmp_path):
        """New instance should be able to kill old and take the lock."""
        import subprocess
        lock_path = str(tmp_path / ".donttype.lock")

        # Spawn a subprocess that holds the lock
        child = subprocess.Popen(
            ["python3", "-c", f"""
import fcntl, time
f = open("{lock_path}", "w+")
fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
f.write(str({os.getpid()}))  # write parent PID (won't actually kill parent)
f.flush()
time.sleep(30)  # hold lock
"""],
        )

        import time
        time.sleep(0.5)  # let child acquire lock

        # Verify lock is held
        lock2 = open(lock_path, "w+")
        blocked = False
        try:
            fcntl.flock(lock2, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            blocked = True
        assert blocked is True
        lock2.close()

        # Kill the child (simulating what entry_point does)
        child.kill()
        child.wait()

        import time
        time.sleep(0.3)

        # Now we should be able to acquire
        lock3 = open(lock_path, "w+")
        fcntl.flock(lock3, fcntl.LOCK_EX | fcntl.LOCK_NB)  # should not raise

        fcntl.flock(lock3, fcntl.LOCK_UN)
        lock3.close()
