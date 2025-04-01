"""Tests for xh package."""

import pytest

from xh import xh


def test_sync_execution():
    """
    Test synchronous execution of a command.

    Uses a simple Python one-liner that prints "hello" and verifies
    that the result behaves like a string with extra attributes.
    """
    result = xh.python('-c', "print('hello')")
    # Check that result is a CommandResult (subclass of str)
    assert isinstance(result, str)
    # stdout should contain "hello" (followed by a newline)
    assert result.strip() == 'hello'


def test_iter_mode():
    """
    Test iterative mode (_iter=True) that returns an iterator over lines.

    The command prints numbers 0, 1, and 2 on separate lines.
    """
    gen = xh.python('-c', 'for i in range(3): print(i)', _iter=True)
    lines = [line.strip() for line in gen if line.strip()]
    assert lines == ['0', '1', '2']


@pytest.mark.asyncio
async def test_async_mode():
    """
    Test asynchronous mode (_async=True) that returns an async generator.

    The command prints numbers 0, 1, and 2 on separate lines.
    """
    lines = []
    async for line in xh.python(
        '-c', 'for i in range(3): print(i)', _async=True
    ):
        if line.strip():
            lines.append(line.strip())
    assert lines == ['0', '1', '2']


def test_background_mode():
    """
    Test background execution (_bg=True) with an output callback.

    A Python one-liner prints numbers 0, 1, and 2 with a slight delay,
    and the callback collects each printed line.
    """
    collected = []

    def callback(line: str) -> None:
        collected.append(line.strip())

    code = (
        'import time\n'
        'for i in range(3):\n'
        '    print(i, flush=True)\n'
        '    time.sleep(0.1)\n'
    )
    proc = xh.python('-c', code, _bg=True, _out=callback)
    proc.wait()
    assert collected == ['0', '1', '2']


def test_command_interface():
    """
    Test command interface.

    Test that accessing an attribute on xh returns a Command instance
    and that it executes as expected.
    """
    # xh.python should be a Command instance.
    assert hasattr(xh.python, '__call__')
    result = xh.python('-c', "print('test')")
    assert result.strip() == 'test'


def test_repr():
    """
    Test __repr__ for Command and CommandResult.

    The __repr__ of a Command should include the word "Command",
    and the __repr__ of a CommandResult should include its stdout.
    """
    cmd = xh.ls
    assert 'Command' in repr(cmd)
    res = xh.python('-c', "print('hello')")
    # Since CommandResult is a subclass of str, its repr is the same as the
    # string repr.
    assert 'hello' in repr(res)
