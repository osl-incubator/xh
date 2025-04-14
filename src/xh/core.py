"""
Core xh module.

xh - A Windows-compatible implementation mimicking the "sh" library API.
If not on Windows, you might simply set:
    from xh import xh, Command
and then use:
    mycmd = xh.mycmd
    result = mycmd("-l", "/some/path")

This implementation supports:
 - Synchronous command execution (using communicate)
 - Background execution (_bg=True) with output callbacks (including interactive
    callbacks)
 - Asynchronous (_async=True) and iterative (_iter=True) interfaces.

Note: This is a minimal reimplementation and may not cover all advanced
features of sh.
"""

import asyncio
import inspect
import subprocess
import threading

from typing import IO, Any, AsyncGenerator, Callable, Generator, Optional


class CommandResult(str):
    """
    Represents the result of a command execution.

    This object behaves like a string (its value is the stdout output),
    but also carries additional attributes such as stderr and exitcode.

    Parameters
    ----------
    stdout : str
        The standard output produced by the command.
    stderr : str
        The standard error produced by the command.
    exitcode : int
        The command's exit code.
    """

    stdout: str
    stderr: str
    exitcode: int

    def __new__(
        cls, stdout: str, stderr: str, exitcode: int
    ) -> 'CommandResult':
        """
        Create a new CommandResult instance.

        Parameters
        ----------
        stdout : str
            The standard output.
        stderr : str
            The standard error.
        exitcode : int
            The command's exit code.

        Returns
        -------
        CommandResult
            A new CommandResult instance.
        """
        obj = super().__new__(cls, stdout)
        obj.stdout = stdout
        obj.stderr = stderr
        obj.exitcode = exitcode
        return obj

    def __repr__(self) -> str:
        """
        Return the canonical string representation of the object.

        Returns
        -------
        str
            The stdout content.
        """
        return super().__repr__()


class RunningCommand:
    """
    Represents a running command process.

    Parameters
    ----------
    process : subprocess.Popen[str]
        The subprocess.Popen instance representing the command.
    stdout_callback : Optional[Callable[..., Any]]
        A callback function for processing STDOUT output.
    stderr_callback : Optional[Callable[..., Any]]
        A callback function for processing STDERR output.
    done_callback : Optional[Callable[..., Any]]
        A callback function that is invoked when the process terminates.
    """

    def __init__(
        self,
        process: subprocess.Popen[str],
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
    stream: IO[str],
    callback: Any,
    process: subprocess.Popen[str],
    stdin: Any,
) -> None:
    """
    Read from a stream line by line and pass each line to the callback.

    If the callback returns True, iteration stops.

    The callback signature is inspected to determine the number of parameters:
      - 1 argument: callback(line)
      - 2 arguments: callback(line, stdin)
      - 3 or more arguments: callback(line, stdin, process)

    If the callback is not callable (e.g. a file-like object such as
    sys.stdout), then lines are written to it.

    Parameters
    ----------
    stream : IO[str]
        The stream (STDOUT or STDERR) to read from.
    callback : Any
        The callback function or file-like object to process each line.
    process : subprocess.Popen[str]
        The process associated with the stream.
    stdin : Any
        The STDIN of the process, used for interactive callbacks.
    """
    if callable(callback):
        sig = inspect.signature(callback)
        num_params = len(sig.parameters)
        use_callback = True
    else:
        use_callback = False

    for line in iter(stream.readline, ''):
        if not line:
            break
        if use_callback:
            if num_params == 1:
                result = callback(line)
            elif num_params == 2:
                result = callback(line, stdin)
            elif num_params >= 3:
                result = callback(line, stdin, process)
            if result is True:
                break
        else:
            callback.write(line)
            callback.flush()
    stream.close()


def _run_command(command: Any, *args: Any, **kwargs: Any) -> Any:
    """
    Wrap subprocess.Popen to emulate sh's API.

    This function supports several special keyword arguments.

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
            _out : Callable or file-like object, optional
                A callback for STDOUT output (can be interactive) or a stream
                to write to.
            _err : Callable or file-like object, optional
                A callback for STDERR output.
            _done : Callable, optional
                A callback invoked when the process terminates.
            _new_session : bool, optional
                If True, launch the process in a new process group.
            _out_bufsize : int, optional
                (Not fully implemented) Buffer size control for STDOUT.
            _err_bufsize : int, optional
                (Not fully implemented) Buffer size control for STDERR.

    Returns
    -------
    Any
        - If _bg is True, returns a RunningCommand instance.
        - If _iter is True, returns an iterator yielding output lines.
        - If _async is True, returns an async generator yielding output lines.
        - Otherwise, waits for command completion and returns a CommandResult.
    """
    _bg: bool = kwargs.pop('_bg', False)
    _async: bool = kwargs.pop('_async', False)
    _iter: bool = kwargs.pop('_iter', False)
    _out: Optional[Any] = kwargs.pop('_out', None)
    _err: Optional[Any] = kwargs.pop('_err', None)
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

    # Use text mode to avoid binary buffering warnings.
    p: subprocess.Popen[str] = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
        creationflags=creationflags,
        bufsize=1,  # line buffered in text mode
        text=True,
        encoding='utf-8',
    )
    rc = RunningCommand(
        p, stdout_callback=_out, stderr_callback=_err, done_callback=_done
    )

    if _bg:
        if _out:
            assert p.stdout is not None
            t = threading.Thread(
                target=read_stream, args=(p.stdout, _out, p, p.stdin)
            )
            t.daemon = True
            t.start()
            rc.stdout_thread = t
        if _err:
            assert p.stderr is not None
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
                stdout_pipe: Optional[IO[str]] = p.stdout
                if stdout_pipe is None:
                    raise RuntimeError('p.stdout is None')
                for line in iter(stdout_pipe.readline, ''):
                    yield line
                stdout_pipe.close()
                p.wait()
                if _done:
                    _done(rc, p.returncode == 0, p.returncode)

            return generator()
        elif _async:

            async def async_generator() -> AsyncGenerator[str, None]:
                """Async generator yielding each line from STDOUT."""
                stdout_pipe: Optional[IO[str]] = p.stdout
                if stdout_pipe is None:
                    raise RuntimeError('p.stdout is None')
                loop = asyncio.get_event_loop()
                while True:
                    line = await loop.run_in_executor(
                        None, stdout_pipe.readline
                    )
                    if not line:
                        break
                    yield line
                stdout_pipe.close()
                ret = p.wait()
                if _done:
                    _done(rc, ret == 0, ret)

            return async_generator()
        else:
            stdout, stderr = p.communicate()
            if _done:
                _done(rc, p.returncode == 0, p.returncode)
            return CommandResult(stdout, stderr, p.returncode)


class Command:
    """
    Represents a command.

    Attributes
    ----------
    name : str
        The name of the command.
    """

    def __init__(self, name: str) -> None:
        """
        Initialize a Command instance.

        Parameters
        ----------
        name : str
            The command name.
        """
        self.name = name

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """
        Execute the command with the given arguments.

        Parameters
        ----------
        *args : Any
            Positional arguments to pass to the command.
        **kwargs : Any
            Keyword arguments to pass to the command.

        Returns
        -------
        Any
            The result of running the command via _run_command.
        """
        return _run_command(self.name, *args, **kwargs)

    def __repr__(self) -> str:
        """
        Return the canonical string representation of the Command.

        Returns
        -------
        str
            A string representation of the command.
        """
        return f'<Command {self.name}>'


class XH:
    """
    Mimics the sh library interface by turning attribute access into commands.

    When an attribute is accessed (e.g. xh.ls), a Command instance is returned.
    """

    def __getattr__(self, name: str) -> Command:
        """
        Return a Command instance corresponding to the attribute name.

        Parameters
        ----------
        name : str
            The name of the command.

        Returns
        -------
        Command
            A Command instance.
        """
        return Command(name)


xh = XH()

__all__ = ['Command', 'CommandResult', 'xh']
