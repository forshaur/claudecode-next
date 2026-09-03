"""Coding agent – tool calling on top of Claude.ai RE Client."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

# ANSI colours
GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"


class ToolExecutor:
    """Executes file/command tools restricted to a workspace."""
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.log_file = self.workspace / "agent.log"
        self.max_read_bytes = 50 * 1024  # 50KB limit

    def _resolve(self, path: str) -> Path:
        p = (self.workspace / path).resolve()
        if not str(p).startswith(str(self.workspace)):
            raise ValueError(f"Path outside workspace: {p}")
        return p

    # -------- Tools --------

    def read_file(self, path: str) -> str:
        p = self._resolve(path)
        if not p.exists():
            return f"ERROR: file not found: {path}"
        try:
            size = p.stat().st_size
            if size > self.max_read_bytes:
                # Truncate and warn
                with p.open("rb") as f:
                    content = f.read(self.max_read_bytes).decode("utf-8", errors="replace")
                return f"{content}\n\n[TRUNCATED: file is {size} bytes, only first {self.max_read_bytes} bytes shown]"
            return p.read_text(encoding="utf-8")
        except Exception as e:
            return f"ERROR reading {path}: {e}"

    def write_file(self, path: str, content: str) -> str:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Wrote {path} ({len(content)} bytes)"

    def list_dir(self, path: str = ".") -> str:
        p = self._resolve(path)
        if not p.is_dir():
            return f"ERROR: not a directory: {path}"
        items = []
        for item in sorted(p.iterdir()):
            items.append(f"{'📁' if item.is_dir() else '📄'} {item.name}")
        return "\n".join(items) or "(empty)"

    def search_content(self, pattern: str, path: str = ".") -> str:
        """Search for pattern in files (grep-like)."""
        p = self._resolve(path)
        if p.is_file():
            files = [p]
        else:
            files = [f for f in p.rglob("*") if f.is_file()]
        results = []
        for f in files:
            try:
                with f.open(encoding="utf-8", errors="ignore") as fp:
                    for i, line in enumerate(fp, 1):
                        if pattern in line:
                            results.append(f"{f.relative_to(self.workspace)}:{i}: {line.strip()}")
            except:
                continue
        if not results:
            return "No matches found."
        # Limit to 50 lines to avoid flooding
        return "\n".join(results[:50]) + (f"\n... and {len(results)-50} more" if len(results)>50 else "")

    def patch_file(self, path: str, search: str, replace: str) -> str:
        """Apply a SEARCH/REPLACE patch to a file."""
        p = self._resolve(path)
        if not p.exists():
            return f"ERROR: file not found: {path}"
        try:
            content = p.read_text(encoding="utf-8")
            if search not in content:
                return "ERROR: search string not found in file."
            new_content = content.replace(search, replace, 1)  # only first occurrence
            p.write_text(new_content, encoding="utf-8")
            return f"Patched {path} (replaced 1 occurrence)"
        except Exception as e:
            return f"ERROR patching {path}: {e}"

    def run_command(self, command: str, stream_output: bool = True) -> str:
        """Run a shell command, with optional live streaming."""
        try:
            # We'll use Popen to capture and optionally stream
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
                print(f"{YELLOW}[Command] {command}{RESET}")
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
            return_code = proc.returncode
            full_output = "".join(output_lines)
            # Truncate for Claude: return last 200 lines + exit code
            lines = full_output.splitlines()
            if len(lines) > 200:
                truncated = "\n".join(lines[-200:])
                result = f"(truncated to last 200 lines)\n{truncated}\n"
            else:
                result = full_output
            result += f"\n[exit code: {return_code}]"
            return result
        except Exception as e:
            return f"ERROR running command: {e}"

    # -------- Logging --------

    def log_action(self, action: str, detail: str = ""):
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {action} {detail}\n")


def parse_response(text: str) -> Dict[str, Any]:
    """Extract JSON tool call from Claude's response."""
    # 1. Try to parse the entire text as JSON
    try:
        data = json.loads(text.strip())
        return data
    except json.JSONDecodeError:
        pass

    # 2. Try to extract from a Markdown code block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. Try to find a raw JSON object (greedy)
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 4. If all else fails, treat as final answer, but if it looks like JSON, try once more
    #    (some models might include leading/trailing whitespace)
    if text.strip().startswith("{") and text.strip().endswith("}"):
        try:
            return json.loads(text.strip())
        except:
            pass

    # 5. Fallback: treat as plain text
    return {"final_answer": text}

class AgentLoop:
    def __init__(
        self,
        creds,
        model: str,
        discrete: bool,
        session_state: dict,
        workspace: Path,
        skip_confirm: bool = False,
    ):
        self.creds = creds
        self.model = model
        self.discrete = discrete
        self.session = session_state
        self.executor = ToolExecutor(workspace)
        self.skip_confirm = skip_confirm

    def _confirm(self, tool_name: str, args: dict) -> bool:
        # Auto-approve read-only tools
        if tool_name in ("read_file", "list_dir", "search_content"):
            return True
        if self.skip_confirm:
            return True
        print(f"\n{YELLOW}[Tool] {tool_name}{RESET}")
        print(f"  args: {json.dumps(args, indent=2)}")
        while True:
            ans = input("  Approve? (y/n) ").strip().lower()
            if ans in ("y", "yes"):
                return True
            if ans in ("n", "no"):
                return False
            print("  Please answer y or n.")

    def process_task(self, user_message: str) -> str:
        """Run the agent loop until final answer."""
        from .http import stream_prompt

        current_msg = user_message
        system_prompt = self._system_prompt()

        while True:
            print(f"{BLUE}[Agent] Sending...{RESET}")
            response = stream_prompt(
                self.creds,
                current_msg,
                model=self.model,
                discrete=self.discrete,
                session_state=self.session,
                quiet=True,
                system_prompt=system_prompt,
            )
            if response is None:
                return "ERROR: Claude returned no response."

            # Parse
            data = parse_response(response)
            if "final_answer" in data:
                final = data["final_answer"]
                print(f"{GREEN}[Agent] Final answer:{RESET}")
                print(final)
                return final

            if "tool" in data:
                tool = data["tool"]
                name = tool.get("name")
                args = tool.get("args", {})
                if "thought" in data:
                    print(f"{BLUE}[Thought] {data['thought']}{RESET}")

                if not self._confirm(name, args):
                    current_msg = f"Tool {name} was rejected by user. Please propose an alternative or final answer."
                    continue

                result = self._execute_tool(name, args)
                self.executor.log_action(name, f"{args} -> {result[:200]}")

                current_msg = f"Tool result for {name}({json.dumps(args)}):\n{result}"
                # loop continues

    def _execute_tool(self, name: str, args: dict) -> str:
        method = getattr(self.executor, name, None)
        if not method:
            return f"ERROR: unknown tool '{name}'"
        try:
            return method(**args)
        except Exception as e:
            return f"ERROR executing {name}: {e}"

    def _system_prompt(self) -> str:
        return f"""You are a coding agent. You can use tools to interact with the filesystem and run commands.
Workspace: {self.executor.workspace}

Available tools:
- read_file(path: str) – read a file (max 50KB)
- write_file(path: str, content: str) – write a file (full content)
- list_dir(path: str = ".") – list directory contents
- search_content(pattern: str, path: str = ".") – search for a string in files
- patch_file(path: str, search: str, replace: str) – replace first occurrence of 'search' with 'replace' in a file
- run_command(command: str) – run a shell command (cwd=workspace)

You must output a JSON object with either:
1. A "tool" field with "name" and "args", and optionally a "thought" field.
2. A "final_answer" field with your final response to the user.

IMPORTANT: Output ONLY the raw JSON object. No markdown code blocks, no extra text, no explanations outside the JSON.
"""

def process_task(creds, user_message, model, discrete, session_state, workspace=".", skip_confirm=False):
    loop = AgentLoop(creds, model, discrete, session_state, Path(workspace), skip_confirm)
    return loop.process_task(user_message)