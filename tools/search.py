import glob
from typing import Dict, Any
from pydantic import BaseModel, Field

from tools.base import Tool

class SearchToolSchema(BaseModel):
    pattern: str = Field(..., description="Glob pattern or file name to search for.")
    directory: str = Field(default=".", description="Directory to search in.")

class SearchTool(Tool):
    name = "search"
    description = "Searches for files matching a pattern."
    args_schema = SearchToolSchema

    def run(self, arguments: Dict[str, Any]) -> Any:
        pattern = arguments.get("pattern")
        directory = arguments.get("directory", ".")

        if not pattern:
            return "Error: Pattern not provided."

        try:
            search_path = f"{directory}/**/{pattern}"
            matches = glob.glob(search_path, recursive=True)
            return "\n".join(matches) if matches else "No files found."
        except Exception as e:
            return f"Search error: {str(e)}"
