"""Main module."""

# xh.py - A Windows-compatible implementation mimicking the "sh" library API.
# If not on Windows, you might simply set:
#     from sh import *
#     xh = sh
#
# This implementation supports:
#  - Synchronous command execution (using communicate)
#  - Background execution (_bg=True) with output callbacks (including interactive callbacks)
#  - Asynchronous (_async=True) and iterative (_iter=True) interfaces.
#
# Note: This is a minimal reimplementation and may not cover all advanced features of sh.

import asyncio
import inspect
import os
import subprocess
import threading


class RunningCommand:
    def __init__(
        self,
        process,
        stdout_callback=None,
        stderr_callback=None,
        done_callback=None,
    ):
        self.process = process
        self.stdout_callback = stdout_callback
        self.stderr_callback = stderr_callback
        self.done_callback = done_callback
        self.stdout_thread = None
        self.stderr_thread = None

    def wait(self):
        if self.stdout_thread:
            self.stdout_thread.join()
        if self.stderr_thread:
            self.stderr_thread.join()
        ret = self.process.wait()
        if self.done_callback:
            self.done_callback(self, ret == 0, ret)
        return ret

    def kill(self):
        self.process.kill()

    def terminate(self):
        self.process.terminate()


def read_stream(stream, callback, process, stdin):
    """
    Reads from a stream line by line and passes each line to the callback.
    If the callback returns True, iteration stops.
    Supports interactive callbacks by checking the callback’s signature:
      - 1 argument: callback(line)
      - 2 arguments: callback(line, stdin)
      - 3 or more arguments: callback(line, stdin, process)
    """
    sig = inspect.signature(callback)
    num_params = len(sig.parameters)
    for line in iter(stream.readline, b''):
        if not line:
            break
        try:
            decoded_line = line.decode()
        except UnicodeDecodeError:
            decoded_line = line
        if num_params == 1:
            result = callback(decoded_line)
        elif num_params == 2:
            result = callback(decoded_line, stdin)
        elif num_params >= 3:
            result = callback(decoded_line, stdin, process)
        if result is True:
            break
    stream.close()


def _run_command(command, *args, **kwargs):
    """
    Internal function that wraps subprocess.Popen to emulate sh’s API.

    Recognized special keyword arguments:
      _bg         : if True, run command in background and process output via callbacks.
      _async      : if True, return an async generator that yields output.
      _iter       : if True, return an iterator that yields output lines.
      _out        : a callback for STDOUT output (can be interactive).
      _err        : a callback for STDERR output.
      _done       : a callback invoked when the process terminates.
      _new_session: if True, launch the process in a new process group.
      _out_bufsize and _err_bufsize: (not fully implemented) buffer size controls.

    For non-background commands, if neither _async nor _iter is provided,
    the function waits for completion and returns (stdout, stderr, exitcode).
    """
    _bg = kwargs.pop('_bg', False)
    _async = kwargs.pop('_async', False)
    _iter = kwargs.pop('_iter', False)
    _out = kwargs.pop('_out', None)
    _err = kwargs.pop('_err', None)
    _done = kwargs.pop('_done', None)
    _new_session = kwargs.pop('_new_session', True)
    _out_bufsize = kwargs.pop('_out_bufsize', 1)
    _err_bufsize = kwargs.pop('_err_bufsize', 1)

    # Build the command list
    cmd = [command] + list(args)

    # On Windows, _new_session can be simulated using CREATE_NEW_PROCESS_GROUP.
    creationflags = 0
    if _new_session and hasattr(subprocess, 'CREATE_NEW_PROCESS_GROUP'):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
        creationflags=creationflags,
        bufsize=1,  # line buffered
    )
    rc = RunningCommand(
        p, stdout_callback=_out, stderr_callback=_err, done_callback=_done
    )

    if _bg:
        if _out:
            t = threading.Thread(
                target=read_stream, args=(p.stdout, _out, p, p.stdin)
            )
            t.daemon = True
            t.start()
            rc.stdout_thread = t
        if _err:
            t = threading.Thread(
                target=read_stream, args=(p.stderr, _err, p, p.stdin)
            )
            t.daemon = True
            t.start()
            rc.stderr_thread = t
        return rc
    else:
        if _iter:
            # Return a generator that yields each line of STDOUT.
            def generator():
                for line in iter(p.stdout.readline, b''):
                    try:
                        decoded_line = line.decode()
                    except UnicodeDecodeError:
                        decoded_line = line
                    yield decoded_line
                p.stdout.close()
                p.wait()
                if _done:
                    _done(rc, p.returncode == 0, p.returncode)

            return generator()
        elif _async:
            # Return an async generator that yields each line from STDOUT.
            async def async_generator():
                loop = asyncio.get_event_loop()
                while True:
                    line = await loop.run_in_executor(None, p.stdout.readline)
                    if not line:
                        break
                    try:
                        decoded_line = line.decode()
                    except UnicodeDecodeError:
                        decoded_line = line
                    yield decoded_line
                p.stdout.close()
                ret = p.wait()
                if _done:
                    _done(rc, ret == 0, ret)

            return async_generator()
        else:
            # Synchronous mode: wait for command to complete and return output.
            stdout, stderr = p.communicate()
            if _done:
                _done(rc, p.returncode == 0, p.returncode)
            try:
                stdout = stdout.decode()
            except Exception:
                pass
            try:
                stderr = stderr.decode()
            except Exception:
                pass
            return stdout, stderr, p.returncode


class XH:
    """
    Mimics the sh library interface by turning attribute access into commands.

    For example, xh.ls("-l", "/some/path") calls
    _run_command("ls", "-l", "/some/path").
    """

    def __getattr__(self, name):
        def command_func(*args, **kwargs):
            return _run_command(name, *args, **kwargs)

        return command_func


# Export the xh object
xh = XH()

if __name__ == '__main__':
    # Simple test: print "hello" using the platform's echo command.
    # (On Windows, "echo" is a built-in command so you might need to adjust; this is just for demonstration.)
    out, err, code = xh.echo('hello')
    print('Output:', out)
    print('Error:', err)
    print('Exit code:', code)
