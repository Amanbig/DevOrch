"""
MCP (Model Context Protocol) client for DevOrch — connects to MCP servers
and exposes their tools alongside built-in tools.

MCP servers are configured in ~/.devorch/config.yaml under the `mcp_servers` key:

    mcp_servers:
      filesystem:
        command: npx
        args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]
      github:
        command: npx
        args: ["-y", "@modelcontextprotocol/server-github"]
        env:
          GITHUB_TOKEN: "ghp_xxx"
      sqlite:
        command: uvx
        args: ["mcp-server-sqlite", "--db-path", "mydb.sqlite"]

Each server communicates via JSON-RPC over stdio.
"""

import json
import os
import subprocess
import threading
import time
from typing import Any

from tools.base import Tool

# ── JSON-RPC helpers ─────────────────────────────────────────────────────────

_MSG_ID = 0
_ID_LOCK = threading.Lock()


def _next_id() -> int:
    global _MSG_ID
    with _ID_LOCK:
        _MSG_ID += 1
        return _MSG_ID


def _jsonrpc_request(method: str, params: dict | None = None, req_id: int | None = None) -> bytes:
    """Build a JSON-RPC 2.0 request."""
    msg = {
        "jsonrpc": "2.0",
        "method": method,
        "id": req_id if req_id is not None else _next_id(),
    }
    if params is not None:
        msg["params"] = params
    return (json.dumps(msg) + "\n").encode("utf-8")


def _jsonrpc_notification(method: str, params: dict | None = None) -> bytes:
    """Build a JSON-RPC 2.0 notification (no id)."""
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    return (json.dumps(msg) + "\n").encode("utf-8")


# ── MCP Server Connection ───────────────────────────────────────────────────


class MCPServer:
    """Manages a connection to a single MCP server process."""

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.cwd = cwd
        self.process: subprocess.Popen | None = None
        self.tools: list[dict] = []
        self.resources: list[dict] = []
        self._lock = threading.Lock()
        self._response_buffer: dict[int, dict] = {}
        self._reader_thread: threading.Thread | None = None
        self._running = False
        self._server_info: dict = {}

    def start(self) -> bool:
        """Start the MCP server process and initialize the connection."""
        try:
            # Build environment
            proc_env = os.environ.copy()
            proc_env.update(self.env)

            cmd = [self.command] + self.args

            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=proc_env,
                cwd=self.cwd,
                bufsize=0,
            )

            self._running = True

            # Start reader thread
            self._reader_thread = threading.Thread(
                target=self._read_loop,
                daemon=True,
                name=f"mcp-reader-{self.name}",
            )
            self._reader_thread.start()

            # Initialize MCP protocol
            if not self._initialize():
                self.stop()
                return False

            # List available tools
            self._list_tools()

            return True

        except FileNotFoundError:
            return False
        except Exception:
            return False

    def stop(self):
        """Stop the MCP server process."""
        self._running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on the MCP server."""
        if not self.process or not self._running:
            return f"Error: MCP server '{self.name}' is not running."

        req_id = _next_id()
        request = _jsonrpc_request(
            "tools/call",
            params={"name": tool_name, "arguments": arguments},
            req_id=req_id,
        )

        try:
            self.process.stdin.write(request)
            self.process.stdin.flush()

            # Wait for response (with timeout)
            response = self._wait_for_response(req_id, timeout=30)
            if response is None:
                return f"Error: Timeout waiting for response from MCP server '{self.name}'."

            if "error" in response:
                err = response["error"]
                return f"Error from MCP server: {err.get('message', str(err))}"

            result = response.get("result", {})

            # MCP tool results contain a "content" array
            content_parts = result.get("content", [])
            output_parts = []
            for part in content_parts:
                if part.get("type") == "text":
                    output_parts.append(part.get("text", ""))
                elif part.get("type") == "image":
                    output_parts.append(f"[Image: {part.get('mimeType', 'unknown')}]")
                else:
                    output_parts.append(str(part))

            return "\n".join(output_parts) if output_parts else str(result)

        except Exception as e:
            return f"Error calling tool on MCP server '{self.name}': {e}"

    def _initialize(self) -> bool:
        """Send MCP initialize handshake."""
        req_id = _next_id()
        request = _jsonrpc_request(
            "initialize",
            params={
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "devorch",
                    "version": "0.1.3",
                },
            },
            req_id=req_id,
        )

        try:
            self.process.stdin.write(request)
            self.process.stdin.flush()

            response = self._wait_for_response(req_id, timeout=10)
            if response is None:
                return False

            if "error" in response:
                return False

            self._server_info = response.get("result", {})

            # Send initialized notification
            notification = _jsonrpc_notification("notifications/initialized")
            self.process.stdin.write(notification)
            self.process.stdin.flush()

            return True

        except Exception:
            return False

    def _list_tools(self):
        """List available tools from the MCP server."""
        req_id = _next_id()
        request = _jsonrpc_request("tools/list", req_id=req_id)

        try:
            self.process.stdin.write(request)
            self.process.stdin.flush()

            response = self._wait_for_response(req_id, timeout=10)
            if response and "result" in response:
                self.tools = response["result"].get("tools", [])
        except Exception:
            self.tools = []

    def _read_loop(self):
        """Background thread that reads responses from the MCP server."""
        try:
            while self._running and self.process and self.process.stdout:
                line = self.process.stdout.readline()
                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                    msg_id = msg.get("id")
                    if msg_id is not None:
                        with self._lock:
                            self._response_buffer[msg_id] = msg
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass
        finally:
            self._running = False

    def _wait_for_response(self, req_id: int, timeout: float = 30) -> dict | None:
        """Wait for a response with the given ID."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if req_id in self._response_buffer:
                    return self._response_buffer.pop(req_id)
            time.sleep(0.05)
        return None


# ── MCP Manager ──────────────────────────────────────────────────────────────


class MCPManager:
    """Manages multiple MCP server connections."""

    def __init__(self):
        self.servers: dict[str, MCPServer] = {}

    def load_from_config(self, mcp_config: dict[str, dict]) -> list[str]:
        """Load and start MCP servers from config.
        Returns list of successfully started server names.
        """
        started = []
        for name, config in mcp_config.items():
            command = config.get("command", "")
            if not command:
                continue

            args = config.get("args", [])
            env = config.get("env", {})
            cwd = config.get("cwd")

            server = MCPServer(name=name, command=command, args=args, env=env, cwd=cwd)
            if server.start():
                self.servers[name] = server
                started.append(name)

        return started

    def get_all_tools(self) -> list["MCPToolProxy"]:
        """Get Tool instances for all tools across all connected MCP servers."""
        tools = []
        for server_name, server in self.servers.items():
            for tool_def in server.tools:
                proxy = MCPToolProxy(
                    server=server,
                    server_name=server_name,
                    tool_def=tool_def,
                )
                tools.append(proxy)
        return tools

    def stop_all(self):
        """Stop all MCP servers."""
        for server in self.servers.values():
            server.stop()
        self.servers.clear()

    def list_servers(self) -> list[dict]:
        """List all connected servers and their tools."""
        result = []
        for name, server in self.servers.items():
            result.append(
                {
                    "name": name,
                    "running": server._running,
                    "tools": [t.get("name", "") for t in server.tools],
                    "server_info": server._server_info,
                }
            )
        return result


# ── MCP Tool Proxy ───────────────────────────────────────────────────────────


class MCPToolProxy(Tool):
    """Wraps an MCP server tool as a DevOrch Tool so it integrates seamlessly."""

    def __init__(self, server: MCPServer, server_name: str, tool_def: dict):
        self._server = server
        self._server_name = server_name
        self._tool_def = tool_def

        # Set tool name with server prefix to avoid conflicts
        self.name = f"mcp_{server_name}_{tool_def.get('name', 'unknown')}"
        self.description = f"[MCP: {server_name}] {tool_def.get('description', 'No description')}"
        self.args_schema = None  # MCP tools use raw JSON schema

    def schema(self) -> dict[str, Any]:
        """Return the tool schema for LLM consumption."""
        input_schema = self._tool_def.get(
            "inputSchema",
            {
                "type": "object",
                "properties": {},
            },
        )

        return {
            "name": self.name,
            "description": self.description,
            "parameters": input_schema,
        }

    def run(self, arguments: dict[str, Any]) -> Any:
        """Execute the tool via the MCP server."""
        original_name = self._tool_def.get("name", "")
        return self._server.call_tool(original_name, arguments)
