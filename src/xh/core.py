"""
Core xh module.

xh.py - A Windows-compatible implementation mimicking the "sh" library API.
If not on Windows, you might simply set:
    from sh import *
    xh = sh

This implementation supports:
 - Synchronous command execution (using communicate)
 - Background execution (_bg=True) with output callbacks
  (including interactive callbacks)
 - Asynchronous (_async=True) and iterative (_iter=True) interfaces.

Note: This is a minimal reimplementation and may not cover all advanced
  features of sh.
"""

import asyncio
import inspect
import subprocess
import threading

from typing import Any, AsyncGenerator, BinaryIO, Callable, Generator, Optional


class RunningCommand:
    """
    Class representing a running command process.

    Parameters
    ----------
    process : subprocess.Popen
        The subprocess.Popen instance representing the command.
    stdout_callback : Optional[Callable[..., Any]], optional
        A callback function for processing STDOUT output.
    stderr_callback : Optional[Callable[..., Any]], optional
        A callback function for processing STDERR output.
    done_callback : Optional[Callable[..., Any]], optional
        A callback function that is invoked when the process terminates.
    """

    def __init__(
        self,
        process: subprocess.Popen,
        stdout_callback: Optional[Callable[..., Any]] = None,
        stderr_callback: Optional[Callable[..., Any]] = None,
        done_callback: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.process = process
        self.stdout_callback = stdout_callback
        self.stderr_callback = stderr_callback
        self.done_callback = done_callback
        self.stdout_thread: Optional[threading.Thread] = None
        self.stderr_thread: Optional[threading.Thread] = None

    def wait(self) -> int:
        """
        Wait for the command to complete.

        Returns
        -------
        int
            The exit code of the process.
        """
        if self.stdout_thread:
            self.stdout_thread.join()
        if self.stderr_thread:
            self.stderr_thread.join()
        ret = self.process.wait()
        if self.done_callback:
            self.done_callback(self, ret == 0, ret)
        return ret

    def kill(self) -> None:
        """Kill the running process."""
        self.process.kill()

    def terminate(self) -> None:
        """Terminate the running process."""
        self.process.terminate()


def read_stream(
    stream: BinaryIO,
    callback: Callable[..., Any],
    process: subprocess.Popen,
    stdin: Any,
) -> None:
    """
    Read from a stream line by line and pass each line to the callback.

    If the callback returns True, the iteration stops.

    The callback signature is inspected to determine the number of parameters:
      - 1 argument: callback(line)
      - 2 arguments: callback(line, stdin)
      - 3 or more arguments: callback(line, stdin, process)

    Parameters
    ----------
    stream : BinaryIO
        The stream (STDOUT or STDERR) to read from.
    callback : Callable[..., Any]
        The callback function to process each line.
    process : subprocess.Popen
        The process associated with the stream.
    stdin : Any
        The STDIN of the process, used for interactive callbacks.
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


def _run_command(command: Any, *args: Any, **kwargs: Any) -> Any:
    """
    Wrap subprocess.Popen to emulate sh's API.

    This function supports several special keyword arguments:

    Parameters
    ----------
    command : Any
        The command to run.
    *args : Any
        Additional arguments for the command.
    **kwargs : Any
        Recognized special keyword arguments:
            _bg : bool, optional
                If True, run the command in the background and process output
                via callbacks.
            _async : bool, optional
                If True, return an async generator that yields output.
            _iter : bool, optional
                If True, return an iterator that yields output lines.
            _out : Callable, optional
                A callback for STDOUT output (can be interactive).
            _err : Callable, optional
                A callback for STDERR output.
            _done : Callable, optional
                A callback invoked when the process terminates.
            _new_session : bool, optional
                If True, launch the process in a new process group.
            _out_bufsize : int, optional
                (Not fully implemented) Buffer size controls for STDOUT.
            _err_bufsize : int, optional
                (Not fully implemented) Buffer size controls for STDERR.

    Returns
    -------
    Any
        - If _bg is True, returns a RunningCommand instance.
        - If _iter is True, returns an iterator yielding output lines.
        - If _async is True, returns an async generator yielding output lines.
        - Otherwise, waits for command completion and returns a tuple
            (stdout, stderr, exitcode).
    """
    _bg: bool = kwargs.pop('_bg', False)
    _async: bool = kwargs.pop('_async', False)
    _iter: bool = kwargs.pop('_iter', False)
    _out: Optional[Callable[..., Any]] = kwargs.pop('_out', None)
    _err: Optional[Callable[..., Any]] = kwargs.pop('_err', None)
    _done: Optional[Callable[..., Any]] = kwargs.pop('_done', None)
    _new_session: bool = kwargs.pop('_new_session', True)
    _out_bufsize: int = kwargs.pop('_out_bufsize', 1)
    _err_bufsize: int = kwargs.pop('_err_bufsize', 1)

    # Build the command list.
    cmd = [command, *list(args)]

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

            def generator() -> Generator[str, None, None]:
                """Generate yielding each line of STDOUT."""
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

            async def async_generator() -> AsyncGenerator[str, None]:
                """Asynchronous generator yielding each line from STDOUT."""
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

    When an attribute is accessed (e.g. xh.ls), a function is returned that,
    when called, invokes _run_command with the attribute name as the command.s

    Methods
    -------
    __getattr__(name: str) -> Callable[..., Any]
        Returns a callable that executes the command with the given name.
    """

    def __getattr__(self, name: str) -> Callable[..., Any]:
        def command_func(*args: Any, **kwargs: Any) -> Any:
            return _run_command(name, *args, **kwargs)

        return command_func


# Export the xh object.
xh = XH()

__all__ = ['xh']
