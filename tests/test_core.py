"""Tests for xh package."""

import time

import pytest


# Import the xh object from your xh module.
from xh import xh


def test_synchronous_execution():
    """Test synchronous execution."""
    # Use the current Python interpreter to print "hello"
    out, err, code = xh.python('-c', "print('hello')")
    assert code == 0
    assert out.strip() == 'hello'
    assert err == ''


def test_iterative_execution():
    """Test iterative execution."""
    # Run a command that prints 0, 1, 2 on separate lines.
    gen = xh.python('-c', 'for i in range(3): print(i)', _iter=True)
    lines = [line.strip() for line in gen if line.strip() != '']
    assert lines == ['0', '1', '2']


@pytest.mark.asyncio
async def test_async_execution():
    """Test async execution."""
    lines = []
    async for line in xh.python(
        '-c', 'for i in range(3): print(i)', _async=True
    ):
        if line:
            lines.append(line.strip())
    assert lines == ['0', '1', '2']


def test_background_callback():
    """Test background callback."""
    # This callback appends every line to a list.
    collected = []

    def callback(line):
        collected.append(line.strip())

    # Use a Python one-liner that prints numbers 0 to 2 with flush.
    code_str = (
        'import time\n'
        'for i in range(3):\n'
        '    print(i, flush=True)\n'
        '    time.sleep(0.1)\n'
    )
    p = xh.python('-c', code_str, _bg=True, _out=callback)
    p.wait()
    assert collected == ['0', '1', '2']


def test_done_callback():
    """Test done callback."""
    # Test that the done callback is invoked with the correct exit code.
    done_called = []

    def done(cmd, success, exit_code):
        done_called.append((success, exit_code))

    out, err, code = xh.python('-c', "print('done')", _done=done)
    # The callback should have been called.
    assert len(done_called) == 1
    success, exit_code = done_called[0]
    assert success is True
    assert exit_code == 0


def test_interactive_callback():
    """
    Test an interactive callback.

    Test an interactive callback that stops further output
    processing when a condition is met."
    """
    collected = []

    # This callback will stop processing after encountering "1".
    def interactive_callback(line):
        collected.append(line.strip())
        if line.strip() == '1':
            return True

    # Print numbers 0 through 4. The callback should stop after "1".
    code_str = 'for i in range(5):\n    print(i)\n'
    p = xh.python('-c', code_str, _bg=True, _out=interactive_callback)
    p.wait()
    # We expect only "0" and "1" to have been collected.
    assert collected == ['0', '1']


def test_kill_process():
    """Test kill process."""
    # Start a process that sleeps for 5 seconds in the background.
    p = xh.python('-c', 'import time; time.sleep(5)', _bg=True)
    # Allow a moment for the process to start.
    time.sleep(0.2)
    p.kill()
    exit_code = p.wait()
    # On termination, the exit code should not be 0.
    assert exit_code != 0
