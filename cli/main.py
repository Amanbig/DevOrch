import os
import typer

from core.agent import Agent
from core.executor import ToolExecutor
from providers.openai import OpenAIProvider
from utils.logger import get_console, print_error, print_success, print_panel
# Import your custom tools
from tools.shell import ShellTool
from tools.filesystem import FilesystemTool
from tools.search import SearchTool

# We need a basic planner for the agent
from core.planner import Planner
from schemas.message import Message
from typing import List

class SimplePlanner(Planner):
    def plan(self, history: List[Message]) -> List[Message]:
        # For a basic agent, the planner just passes the history to the LLM
        # We could inject system prompts here
        system_prompt = Message(
            role="system", 
            content="You are DevPilot, an AI coding assistant. You have access to tools to interact with the local machine. Use them to help the user."
        )
        return [system_prompt] + history

app = typer.Typer(help="DevPilot - Your AI Coding Assistant")
console = get_console()

@app.command()
def ask(
    prompt: str = typer.Argument(..., help="The prompt or question for DevPilot"),
    provider: str = typer.Option("openai", help="LLM Provider to use (openai, gemini, etc)"),
    model: str = typer.Option("gpt-4o", help="Model name to use")
):
    """
    Ask DevPilot a single question or give it a task.
    """
    if provider.lower() == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print_error("Please set OPENAI_API_KEY environment variable")
            raise typer.Exit(1)
            
        llm = OpenAIProvider(model=model, api_key=api_key)
    else:
        print_error(f"Provider {provider} is not fully implemented yet.")
        raise typer.Exit(1)
        
    tools = [
        ShellTool(),
        FilesystemTool(),
        SearchTool()
    ]
    
    executor = ToolExecutor(tools=tools)
    planner = SimplePlanner()
    
    agent = Agent(
        provider=llm,
        planner=planner,
        executor=executor,
        tools=tools
    )
    
    console.print(f"[bold blue]DevPilot is thinking...[/bold blue]")
    try:
        result = agent.run(prompt, max_iterations=15)
        print_success("Response:")
        # For full markdown rendering you still need rich context or markdown parse.
        # We'll just show it via print_panel
        print_panel(result, title="DevPilot Response", border_style="green")
    except Exception as e:
        print_error(str(e))

@app.command()
def repl(
    provider: str = typer.Option("openai", help="LLM Provider to use"),
    model: str = typer.Option("gpt-4o", help="Model name to use")
):
    """
    Start an interactive DevPilot REPL session.
    """
    if provider.lower() == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print_error("Please set OPENAI_API_KEY environment variable")
            raise typer.Exit(1)
        llm = OpenAIProvider(model=model, api_key=api_key)
    else:
        print_error(f"Provider {provider} is not fully implemented yet.")
        raise typer.Exit(1)
        
    tools = [ShellTool(), FilesystemTool(), SearchTool()]
    executor = ToolExecutor(tools=tools, require_confirmation=True)
    planner = SimplePlanner()
    
    agent = Agent(provider=llm, planner=planner, executor=executor, tools=tools)

    print_panel("Welcome to DevPilot REPL!\nType 'exit' or 'quit' to leave.\nType your message below.", title="DevPilot", border_style="blue", fit=True)
    
    while True:
        try:
            # Use Typer's prompt for basic input, could upgrade to prompt_toolkit later
            user_input = typer.prompt("You")
            
            if user_input.lower() in ("exit", "quit", "q"):
                print_warning("Goodbye!")
                break
                
            if not user_input.strip():
                continue
                
            result = agent.run(user_input, max_iterations=15)
            print_panel(result, title="DevPilot", border_style="green")
            
        except typer.Abort:
            print_warning("Aborted.")
            break
        except Exception as e:
            print_error(str(e))

def main():
    app()

if __name__ == "__main__":
    main()
