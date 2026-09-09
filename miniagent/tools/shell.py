"""Named argv commands, not a shell interpreter or an operating-system sandbox."""

import os
import selectors
import signal
import subprocess
import time

from pydantic import Field

from miniagent.state.models import StrictModel, ToolResult
from miniagent.tools.base import ToolContext, workspace_digest


class ShellArgs(StrictModel):
    command: str = Field(min_length=1, max_length=80)


def kill_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_command(argv: list[str], context: ToolContext) -> ToolResult:
    output = bytearray()
    truncated = False
    timed_out = False
    timeout = context.policy.command_timeout_seconds
    if context.deadline is not None:
        timeout = min(timeout, context.deadline - time.time())
    if timeout <= 0:
        return ToolResult(success=False, error="Runtime deadline reached", metadata={"timed_out": True})
    deadline = time.monotonic() + timeout
    process = subprocess.Popen(
        argv, cwd=context.workspace.resolve(), shell=False, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
        env={"PATH": os.defpath, "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert process.stdout is not None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() >= deadline:
                    timed_out = True
                    kill_group(process)
                    break
                if process.poll() is not None:
                    kill_group(process)  # descendants must not survive the parent
                for key, _ in selector.select(timeout=min(0.05, max(0, deadline - time.monotonic()))):
                    block = os.read(key.fileobj.fileno(), 65536)
                    if not block:
                        selector.unregister(key.fileobj)
                        continue
                    remaining = context.output_limit - len(output)
                    output.extend(block[:remaining])
                    truncated |= len(block) > remaining
            # A process may close stdout and continue running.
            try:
                process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        kill_group(process)
        process.wait()
        process.stdout.close()
    return ToolResult(
        success=process.returncode == 0 and not timed_out,
        output=output.decode("utf-8", errors="replace"), exit_code=process.returncode,
        error="Command timed out" if timed_out else (f"Command exited {process.returncode}" if process.returncode else None),
        metadata={"truncated": truncated, "timed_out": timed_out},
    )


class Shell:
    name = "shell"
    description = "Run a configured command by name. Arguments: command (string). No arbitrary shell text."
    args_model = ShellArgs

    def execute(self, args: ShellArgs, context: ToolContext) -> ToolResult:
        argv = context.policy.commands.get(args.command)
        if argv is None:
            raise ValueError("Command is not configured")
        before = workspace_digest(context)
        result = run_command(argv, context)
        after = workspace_digest(context)
        if before != after:
            result.success = False
            result.error = "Source files changed during verification"
        elif result.success:
            result.metadata["verification_digest"] = after
        return result
