import subprocess
from typing import Dict, Any
from pydantic import BaseModel, Field

from tools.base import Tool

class ShellToolSchema(BaseModel):
    command: str = Field(..., description="The shell command to execute.")

class ShellTool(Tool):
    name = "shell"
    description = "Executes a shell command on the user's system."
    args_schema = ShellToolSchema

    def run(self, arguments: Dict[str, Any]) -> Any:
        try:
            command = arguments.get("command")
            if not command:
                return "Error: No command provided."
            
            # Execute the command
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True,
                check=False
            )
            
            output = ""
            if result.stdout:
                output += f"STDOUT:\n{result.stdout}\n"
            if result.stderr:
                output += f"STDERR:\n{result.stderr}\n"
                
            return output if output else f"Command completed with exit code {result.returncode}."
        except Exception as e:
            return f"Failed to execute command: {str(e)}"
