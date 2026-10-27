"""
Start a pipeline script on Kenny's PC so it runs NOW (2026-10-26 perf fix).

Why: a process started with subprocess.Popen from inside Resolve's scripting
connection (Claude's run_script_unsafe) used to sit frozen until the NEXT call
into that connection (measured 300 s for a two-line script; zz tests started
3-4 min late). Cause: the child inherited the connection's stdin pipe, and
Windows blocks a new process on a pipe that another thread is reading until
that read finishes (= the next message). With stdin/stdout/stderr on DEVNULL
it starts in ~0.02 s.

Stays a normal child of the connection (inside the Claude app's package), so it
sees the same Python packages (Pillow etc.) and npm caches. NOT WMI: a process
started through WMI runs outside the package and can't import Pillow.

Use from run_script_unsafe:
    exec(open(r"C:\\Users\\YOURNAME\\scoreboard-pipeline\\launch.py").read())
    pid = launch([PY, W + r"\\run-match.py", "--recent"])
"""
import subprocess

def launch(args, cwd=r"C:\Users\YOURNAME\scoreboard-pipeline", env=None):
    """args: list like for Popen -> process id; detached, no window, no inherited pipes"""
    p = subprocess.Popen([str(a) for a in args], cwd=cwd, env=env,
                         creationflags=0x00000008 | 0x08000000,       # DETACHED_PROCESS | CREATE_NO_WINDOW
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True)
    return p.pid
