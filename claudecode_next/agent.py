"""Coding agent – tool calling on top of Claude.ai RE Client."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any

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
        self.max_read_bytes = 50 * 1024

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
            size = p.stat().st_size
            if size > self.max_read_bytes:
                with p.open("rb") as f:
                    content = f.read(self.max_read_bytes).decode("utf-8-sig", errors="replace")
                return f"{content}\n\n[TRUNCATED: file is {size} bytes, only first {self.max_read_bytes} bytes shown]"
            return p.read_text(encoding="utf-8-sig")
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
            new_content = content.replace(search, replace, 1)
            p.write_text(new_content, encoding="utf-8")
            return f"Patched {path} (replaced 1 occurrence)"
        except Exception as e:
            return f"ERROR patching {path}: {e}"

    def run_command(self, command: str, stream_output: bool = True) -> str:
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


def parse_response(text: str) -> Dict[str, Any]:
    """Extract JSON tool call from Claude's response."""
    # 1. Try full JSON parse
    try:
        data = json.loads(text.strip())
        return data
    except json.JSONDecodeError:
        pass

    # 2. Try markdown code block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. Try raw braces (greedy)
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 4. If the whole text looks like JSON, try one more time
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            return json.loads(stripped)
        except:
            pass

    # 5. Fallback: plain text
    return {"final_answer": text}


class AgentLoop:
    def __init__(self, creds, model: str, discrete: bool, session_state: dict, workspace: Path, skip_confirm: bool = False):
        self.creds = creds
        self.model = model
        self.discrete = discrete
        self.session = session_state
        self.executor = ToolExecutor(workspace)
        self.skip_confirm = skip_confirm

    def _confirm(self, tool_name: str, args: dict) -> bool:
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
        from .http import stream_prompt

        # Start a fresh conversation for this task (no memory from previous tasks)
        self.session["conv_id"] = None
        self.session["created"] = False

        current_msg = user_message
        system_prompt = self._system_prompt()
        is_first_turn = True
        consecutive_failures = 0  # count non-JSON responses

        while True:
            print(f"{BLUE}[Agent] Sending...{RESET}")

            # If we've had two non-JSON responses, resend system prompt as a reminder
            if consecutive_failures >= 2:
                print(f"{YELLOW}[Agent] Re-sending system prompt (Claude forgot its role){RESET}")
                is_first_turn = True
                consecutive_failures = 0

            response = stream_prompt(
                self.creds,
                current_msg,
                model=self.model,
                discrete=self.discrete,
                session_state=self.session,
                quiet=True,
                system_prompt=system_prompt if is_first_turn else None,
            )
            is_first_turn = False

            if response is None:
                return "ERROR: Claude returned no response."

            data = parse_response(response)

            # Detect conversational refusal (Claude forgot its role)
            if "final_answer" in data:
                final_text = data["final_answer"]
                # If it sounds like a refusal, treat as failure
                if any(phrase in final_text.lower() for phrase in ["i can't", "i don't have access", "i don't see", "can't access"]):
                    print(f"{YELLOW}[Agent] Claude gave a conversational refusal. Resetting...{RESET}")
                    consecutive_failures += 1
                    # Send a strong reminder as the next user message
                    current_msg = f"REMINDER: You are a tool-calling agent. Output JSON only. Do not say you can't. Use tools. User request: {user_message}"
                    continue

                # Otherwise it's a proper final answer
                print(f"{GREEN}[Agent] Final answer:{RESET}")
                print(final_text)
                return final_text

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

                # Tool result as next user message
                current_msg = f"Tool result for {name}({json.dumps(args)}):\n{result}"
                consecutive_failures = 0  # reset on success

    def _execute_tool(self, name: str, args: dict) -> str:
        method = getattr(self.executor, name, None)
        if not method:
            return f"ERROR: unknown tool '{name}'"
        try:
            return method(**args)
        except Exception as e:
            return f"ERROR executing {name}: {e}"

    def _system_prompt(self) -> str:
        """Load system prompt from config file, falling back to a minimal default."""
        config_path = Path(__file__).parent / "system_prompt.txt"
        if config_path.exists():
            return config_path.read_text(encoding="utf-8").strip()
        # Fallback default if file is missing
        return (
            "Role: Local CLI tool-calling executor. !CHAT. !ASSUME.\n"
            "Output RAW JSON ONLY. Use tools to fulfill requests.\n"
            "Action: {\"thought\": \"...\", \"tool\": {\"name\": \"...\", \"args\": {}}}\n"
            "Final: {\"final_answer\": \"...\"}"
        )

def process_task(creds, user_message, model, discrete, session_state, workspace=".", skip_confirm=False):
    loop = AgentLoop(creds, model, discrete, session_state, Path(workspace), skip_confirm)
    return loop.process_task(user_message)