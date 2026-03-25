"""PyInstaller entry point — runs dictate as a package."""
import sys
import os
import fcntl

# Log to file so we can debug the bundled app
log_path = os.path.expanduser("~/Library/Logs/Dictate.log")
os.makedirs(os.path.dirname(log_path), exist_ok=True)
sys.stdout = sys.stderr = open(log_path, "a")

# Help MLX find its metallib inside the PyInstaller bundle
if getattr(sys, '_MEIPASS', None):
    bundle_dir = sys._MEIPASS
    # Check multiple possible locations
    for candidate in [
        os.path.join(bundle_dir, 'mlx.metallib'),
        os.path.join(bundle_dir, 'mlx', 'lib', 'mlx.metallib'),
    ]:
        if os.path.exists(candidate):
            os.environ['MLX_METAL_LIB_PATH'] = candidate
            print(f"Set MLX_METAL_LIB_PATH={candidate}", file=sys.stderr)
            break
    else:
        print(f"WARNING: mlx.metallib not found in {bundle_dir}", file=sys.stderr)

# Single-instance guard — prevent multiple copies from running
_lock_path = os.path.expanduser("~/Library/Logs/.dictate.lock")
_lock_file = open(_lock_path, "w")
try:
    fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    # Another instance is already running
    print("Dictate is already running. Exiting.", file=sys.stderr)
    sys.exit(0)

from dictate.__main__ import main

if __name__ == "__main__":
    main()
