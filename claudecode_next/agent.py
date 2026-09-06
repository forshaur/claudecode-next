"""Coding agent – tool calling on top of Claude.ai RE Client or DeepSeek."""
import json
import os
import re
import subprocess
import sys
import time
import difflib
import threading
from pathlib import Path
from typing import Dict, Any

from rich.console import Console
from rich.syntax import Syntax
from rich.panel import Panel

console = Console()

# Import provider abstraction
from .providers import get_stream_function

# Global streaming status (shared with main)
streaming_status = {'active': False, 'start': 0.0}


class ToolExecutor:
    """Executes file/command tools restricted to a workspace."""
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.log_file = self.workspace / "agent.log"
        self.max_read_bytes = 50 * 1024
        self.confirm_required = True

    def _resolve(self, path: str) -> Path:
        p = (self.workspace / path).resolve()
        if not str(p).startswith(str(self.workspace)):
            raise ValueError(f"Path outside workspace: {p}")
        return p

    def read_file(self, path: str) -> str:
        p = self._resolve(path)
        if not p.exists():
            return f"ERROR: file not found: {path}"
        try:
            content = p.read_text(encoding="utf-8-sig")
            ext = p.suffix.lstrip('.') or 'txt'
            syntax = Syntax(content, ext, theme="monokai", line_numbers=True)
            from io import StringIO
            from rich.console import Console as RichConsole
            f = StringIO()
            rich_console = RichConsole(file=f, color_system="truecolor")
            rich_console.print(syntax)
            return f.getvalue()
        except Exception as e:
            return f"ERROR reading {path}: {e}"

    def write_file(self, path: str, content: str) -> str:
        p = self._resolve(path)
        if p.exists() and self.confirm_required:
            old = p.read_text(encoding="utf-8-sig") if p.exists() else ""
            if old != content:
                diff = difflib.unified_diff(
                    old.splitlines(),
                    content.splitlines(),
                    fromfile=f'a/{path}',
                    tofile=f'b/{path}',
                    lineterm=''
                )
                diff_text = '\n'.join(diff)
                if diff_text:
                    console.print(Panel(diff_text, title="Diff Preview", border_style="yellow"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Wrote {path} ({len(content)} bytes)"

    def list_dir(self, path: str = ".") -> str:
        p = self._resolve(path)
        if not p.is_dir():
            return f"ERROR: not a directory: {path}"
        items = []
        for item in sorted(p.iterdir()):
            size = item.stat().st_size if item.is_file() else 0
            size_str = f" ({size:,} B)" if size else ""
            items.append(f"{'📁' if item.is_dir() else '📄'} {item.name}{size_str}")
        return "\n".join(items) or "(empty)"

    def search_content(self, pattern: str, path: str = ".") -> str:
        p = self._resolve(path)
        if p.is_file():
            files = [p]
        else:
            files = [f for f in p.rglob("*") if f.is_file()]
        results = []
        for f in files:
            try:
                with f.open(encoding="utf-8-sig", errors="ignore") as fp:
                    for i, line in enumerate(fp, 1):
                        if pattern in line:
                            results.append(f"{f.relative_to(self.workspace)}:{i}: {line.strip()}")
            except:
                continue
        if not results:
            return "No matches found."
        return "\n".join(results[:50]) + (f"\n... and {len(results)-50} more" if len(results)>50 else "")

    def patch_file(self, path: str, search: str, replace: str) -> str:
        p = self._resolve(path)
        if not p.exists():
            return f"ERROR: file not found: {path}"
        try:
            content = p.read_text(encoding="utf-8-sig")
            if search not in content:
                return "ERROR: search string not found in file."
            if self.confirm_required:
                new_content = content.replace(search, replace, 1)
                diff = difflib.unified_diff(
                    content.splitlines(),
                    new_content.splitlines(),
                    fromfile=f'a/{path}',
                    tofile=f'b/{path}',
                    lineterm=''
                )
                diff_text = '\n'.join(diff)
                if diff_text:
                    console.print(Panel(diff_text, title="Patch Diff", border_style="yellow"))
            new_content = content.replace(search, replace, 1)
            p.write_text(new_content, encoding="utf-8")
            return f"Patched {path} (replaced 1 occurrence)"
        except Exception as e:
            return f"ERROR patching {path}: {e}"

    def run_command(self, command: str, stream_output: bool = True) -> str:
        # Security warning: shell=True is risky; we trust the user confirmation.
        # In a production setting, implement a whitelist or use shell=False.
        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=self.workspace,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            output_lines = []
            if stream_output:
                console.print(f"[yellow][Command] {command}[/]")
            while True:
                line = proc.stdout.readline()
                if not line and proc.poll() is not None:
                    break
                if line:
                    if stream_output:
                        sys.stdout.write(line)
                        sys.stdout.flush()
                    output_lines.append(line)
            proc.wait()
            full_output = "".join(output_lines)
            lines = full_output.splitlines()
            if len(lines) > 200:
                truncated = "\n".join(lines[-200:])
                result = f"(truncated to last 200 lines)\n{truncated}\n"
            else:
                result = full_output
            result += f"\n[exit code: {proc.returncode}]"
            return result
        except Exception as e:
            return f"ERROR running command: {e}"

    def log_action(self, action: str, detail: str = ""):
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {action} {detail}\n")

    # ----- Helper for diff preview (used by confirm) -----
    def _preview_diff(self, tool_name: str, args: dict) -> str:
        """Generate a unified diff preview for write/patch operations without executing them."""
        path = args.get("path")
        if not path:
            return ""
        p = self._resolve(path)
        if not p.exists() and tool_name == "patch_file":
            return f"ERROR: file not found: {path}"
        try:
            old_content = p.read_text(encoding="utf-8-sig") if p.exists() else ""
            if tool_name == "write_file":
                new_content = args.get("content", "")
            elif tool_name == "patch_file":
                search = args.get("search", "")
                replace = args.get("replace", "")
                if search not in old_content:
                    return "ERROR: search string not found in file."
                new_content = old_content.replace(search, replace, 1)
            else:
                return ""
            diff = difflib.unified_diff(
                old_content.splitlines(),
                new_content.splitlines(),
                fromfile=f'a/{path}',
                tofile=f'b/{path}',
                lineterm=''
            )
            return '\n'.join(diff)
        except Exception as e:
            return f"Error generating diff: {e}"


def parse_response(text: str) -> Dict[str, Any]:
    """Extract JSON tool call from model response, robustly."""
    # 1. Strip Markdown code fences
    text = re.sub(r"```(?:json)?\s*|\s*```", "", text, flags=re.DOTALL).strip()

    def try_parse(candidate):
        try:
            data = json.loads(candidate)
            if 'tool' in data or 'final_answer' in data:
                return data
            if 'name' in data and 'args' in data:
                return {'tool': data}
        except json.JSONDecodeError:
            return None

    # 2. Try direct parse
    data = try_parse(text)
    if data:
        return data

    # 3. Scan for balanced JSON objects (handles nested braces and strings)
    start = text.find('{')
    while start != -1:
        brace_count = 0
        in_string = False
        escape = False
        for i, ch in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
            if not in_string:
                if ch == '{':
                    brace_count += 1
                elif ch == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        candidate = text[start:i+1]
                        data = try_parse(candidate)
                        if data:
                            return data
                        start = text.find('{', i+1)
                        break
        else:
            break

    # 4. Fallback: greedily match a JSON-like structure
    match = re.search(r"(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})", text, re.DOTALL)
    if match:
        data = try_parse(match.group(1))
        if data:
            return data

    return {"final_answer": text.strip()}


class AgentLoop:
    def __init__(self, creds, model: str, discrete: bool, session_state: dict,
                 workspace: Path, provider: str = "claude",
                 skip_confirm: bool = False):
        self.creds = creds
        self.model = model
        self.discrete = discrete
        self.session = session_state
        self.executor = ToolExecutor(workspace)
        self.skip_confirm = skip_confirm
        self.confirm_required = not skip_confirm
        self.provider = provider
        self.stream_fn = get_stream_function(provider)

    def _confirm(self, tool_name: str, args: dict) -> bool:
        if tool_name in ("read_file", "list_dir", "search_content"):
            return True
        if not self.confirm_required:
            return True

        # Show diff preview for write/patch
        preview = ""
        if tool_name in ("write_file", "patch_file"):
            preview = self.executor._preview_diff(tool_name, args)

        from prompt_toolkit import prompt
        from prompt_toolkit.validation import Validator, ValidationError
        class YesNoValidator(Validator):
            def validate(self, document):
                text = document.text.lower()
                if text not in ('y', 'yes', 'n', 'no'):
                    raise ValidationError(message="Please answer y or n")
        console.print(f"\n[yellow][Tool] {tool_name}[/]")
        console.print(f"  args: {json.dumps(args, indent=2)}")
        if preview:
            console.print(Panel(preview, title="Diff Preview", border_style="yellow"))
        ans = prompt("  Approve? (y/n) ", validator=YesNoValidator()).strip().lower()
        return ans in ('y', 'yes')

    def process_task(self, user_message: str) -> str:
        current_msg = user_message
        system_prompt = self._system_prompt()
        is_first_turn = True
        consecutive_failures = 0

        # Spinner thread for active feedback
        stop_spinner = threading.Event()
        def spinner():
            chars = "⣾⣽⣻⢿⡿⣟⣯⣷"
            i = 0
            while not stop_spinner.is_set():
                sys.stdout.write(f"\r[Agent] Thinking {chars[i % len(chars)]} ")
                sys.stdout.flush()
                time.sleep(0.15)
                i += 1
            # Clear spinner line
            sys.stdout.write("\r" + " " * 30 + "\r")
            sys.stdout.flush()

        while True:
            console.print(f"[blue][Agent] Sending...[/]")
            if consecutive_failures >= 2:
                console.print(f"[yellow][Agent] Re-sending system prompt (model forgot its role)[/]")
                is_first_turn = True
                consecutive_failures = 0

            # Start spinner
            stop_spinner.clear()
            spinner_thread = threading.Thread(target=spinner)
            spinner_thread.daemon = True
            spinner_thread.start()

            import time as ttime
            streaming_status['active'] = True
            streaming_status['start'] = ttime.time()
            try:
                response = self.stream_fn(
                    self.creds,
                    current_msg,
                    model=self.model,
                    discrete=self.discrete,
                    session_state=self.session,
                    quiet=True,
                    system_prompt=system_prompt if is_first_turn else None,
                )
            except Exception as e:
                console.print(f"[red]Streaming error: {e}[/]")
                return f"ERROR: {e}"
            finally:
                streaming_status['active'] = False
                stop_spinner.set()
                spinner_thread.join(timeout=0.5)

            is_first_turn = False

            if response is None:
                return "ERROR: Model returned no response."

            data = parse_response(response)

            if "final_answer" in data:
                final_text = data["final_answer"]
                # Unescape newlines and clean up
                if isinstance(final_text, str):
                    # Replace literal \n with actual newlines
                    final_text = final_text.replace('\\n', '\n')
                    # Remove surrounding quotes if any
                    if final_text.startswith('"') and final_text.endswith('"'):
                        final_text = final_text[1:-1]
                    # Try to parse nested JSON
                    nested = parse_response(final_text)
                    if "final_answer" in nested and nested["final_answer"] != final_text:
                        final_text = nested["final_answer"]

                if any(phrase in final_text.lower() for phrase in ["i can't", "i don't have access", "i don't see", "can't access"]):
                    console.print(f"[yellow][Agent] Model gave a conversational refusal. Resetting...[/]")
                    consecutive_failures += 1
                    current_msg = f"REMINDER: You are a tool-calling agent. Output JSON only. Do not say you can't. Use tools. User request: {user_message}"
                    continue

                console.print(f"[green][Agent] Final answer:[/]")
                console.print(final_text)
                return final_text

            if "tool" in data:
                tool = data["tool"]
                name = tool.get("name")
                args = tool.get("args", {})
                if "thought" in data:
                    console.print(f"[blue][Thought] {data['thought']}[/]")

                if not self._confirm(name, args):
                    current_msg = f"Tool {name} was rejected by user. Please propose an alternative or final answer."
                    continue

                result = self._execute_tool(name, args)
                self.executor.log_action(name, f"{args} -> {result[:200]}")

                current_msg = f"Tool result for {name}({json.dumps(args)}):\n{result}"
                consecutive_failures = 0

    def _execute_tool(self, name: str, args: dict) -> str:
        method = getattr(self.executor, name, None)
        if not method:
            return f"ERROR: unknown tool '{name}'"
        try:
            return method(**args)
        except Exception as e:
            return f"ERROR executing {name}: {e}"

    def _system_prompt(self) -> str:
        config_path = Path(__file__).parent / "system_prompt.txt"
        if config_path.exists():
            return config_path.read_text(encoding="utf-8").strip()
        return (
            "Role: Local CLI tool-calling executor. !CHAT. !ASSUME.\n"
            "Output RAW JSON ONLY. Use tools to fulfill requests.\n"
            "Action: {\"thought\": \"...\", \"tool\": {\"name\": \"...\", \"args\": {}}}\n"
            "Final: {\"final_answer\": \"...\"}"
        )


def process_task(creds, user_message, model, discrete, session_state,
                 workspace=".", provider="claude", skip_confirm=False):
    loop = AgentLoop(creds, model, discrete, session_state, Path(workspace),
                     provider=provider, skip_confirm=skip_confirm)
    return loop.process_task(user_message)