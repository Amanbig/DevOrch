import os
import typer
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from core.agent import Agent
from core.executor import ToolExecutor
from providers.openai import OpenAIProvider
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
console = Console()

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
            console.print("[bold red]Please set OPENAI_API_KEY environment variable[/bold red]")
            raise typer.Exit(1)
            
        llm = OpenAIProvider(model=model, api_key=api_key)
    else:
        console.print(f"[bold red]Provider {provider} is not fully implemented yet.[/bold red]")
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
        console.print("\n[bold green]Response:[/bold green]")
        console.print(Markdown(result))
    except Exception as e:
        console.print(f"\n[bold red]Error: {str(e)}[/bold red]")

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
            console.print("[bold red]Please set OPENAI_API_KEY environment variable[/bold red]")
            raise typer.Exit(1)
        llm = OpenAIProvider(model=model, api_key=api_key)
    else:
        console.print(f"[bold red]Provider {provider} is not fully implemented yet.[/bold red]")
        raise typer.Exit(1)
        
    tools = [ShellTool(), FilesystemTool(), SearchTool()]
    executor = ToolExecutor(tools=tools, require_confirmation=True)
    planner = SimplePlanner()
    
    agent = Agent(provider=llm, planner=planner, executor=executor, tools=tools)

    console.print(Panel.fit("[bold green]Welcome to DevPilot REPL![/bold green]\nType 'exit' or 'quit' to leave.\nType your message below.", border_style="blue"))
    
    while True:
        try:
            # Use Typer's prompt for basic input, could upgrade to prompt_toolkit later
            user_input = typer.prompt("You")
            
            if user_input.lower() in ("exit", "quit", "q"):
                console.print("[yellow]Goodbye![/yellow]")
                break
                
            if not user_input.strip():
                continue
                
            result = agent.run(user_input, max_iterations=15)
            console.print(Panel(Markdown(result), title="DevPilot", border_style="green"))
            
        except typer.Abort:
            console.print("\n[yellow]Aborted.[/yellow]")
            break
        except Exception as e:
            console.print(f"\n[bold red]Error: {str(e)}[/bold red]")

def main():
    app()

if __name__ == "__main__":
    main()
