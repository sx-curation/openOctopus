"""
Investment Analysis Agent — conversational REPL.

Usage:
    python main.py

Enter a stock ticker (e.g. AAPL, NVDA) or a natural language question
(e.g. "Analyze Microsoft's latest quarter").
"""
from rich.console import Console
from rich.markdown import Markdown
from rich.rule import Rule

from agent import investment_run_analysis

console = Console()


def main() -> None:
    console.print(Rule("[bold blue]Investment Analysis Agent[/bold blue]"))
    console.print(
        "[dim]Powered by Claude claude-sonnet-4-6 · Yahoo Finance · FMP · SEC EDGAR[/dim]\n"
        "Type a ticker or question. Type [bold]quit[/bold] to exit.\n"
    )

    while True:
        try:
            user_input = console.input("[bold green]You:[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            console.print("[dim]Goodbye.[/dim]")
            break

        console.print("\n[dim]Analyzing… this may take 15–30 seconds[/dim]\n")
        try:
            result = investment_run_analysis(user_input)
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}\n")
            continue

        console.print(Markdown(result))
        console.print(Rule())
        console.print()


if __name__ == "__main__":
    main()
