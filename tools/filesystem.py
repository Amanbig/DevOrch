import os
from typing import Dict, Any, Literal
from pydantic import BaseModel, Field

from tools.base import Tool

class FilesystemToolSchema(BaseModel):
    action: Literal["read", "write", "list"] = Field(..., description="Action to perform.")
    path: str = Field(..., description="Path to the file or directory.")
    content: str = Field(default="", description="Content to write (only for 'write' action).")

class FilesystemTool(Tool):
    name = "filesystem"
    description = "Reads, writes, or lists files and directories."
    args_schema = FilesystemToolSchema

    def run(self, arguments: Dict[str, Any]) -> Any:
        action = arguments.get("action")
        path = arguments.get("path")
        content = arguments.get("content", "")

        if not path:
            return "Error: Path not provided."

        try:
            if action == "read":
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            elif action == "write":
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                return f"Successfully wrote to {path}"
            elif action == "list":
                if not os.path.exists(path):
                    return f"Error: Path {path} does not exist."
                items = os.listdir(path)
                return "\n".join(items) if items else "Directory is empty."
            else:
                return f"Error: Unknown action '{action}'"
        except Exception as e:
            return f"Filesystem error: {str(e)}"
