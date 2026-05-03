"""
Policy Monitor Demo Script
==========================
Demonstrates the PolicyMonitoringAgent end-to-end.

Usage:
    python scripts/policy_monitor_demo.py \\
        --jurisdiction EU \\
        --keyword "AI Act" \\
        --from 2024-01-01 \\
        --to 2026-04-12 \\
        --limit 10 \\
        --sources eurlex \\
        --out out.md

Requires:
    POLICY_MONITORING_USER_AGENT env var (or default in config/settings.py)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Make sure project root is on sys.path when run from scripts/
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from agent.policy_monitoring import PolicyMonitoringAgent
from rich.console import Console
from rich.markdown import Markdown
from rich.rule import Rule

console = Console()

SOURCE_ALIASES = {
    "eurlex": "EUR_LEX",
    "eur_lex": "EUR_LEX",
    "fr": "FEDERAL_REGISTER",
    "federal_register": "FEDERAL_REGISTER",
    "sec": "SEC",
    "edgar": "SEC",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Policy Monitoring Agent — fetch and display regulatory updates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--jurisdiction",
        choices=["EU", "US", "ALL"],
        default="ALL",
        help="Jurisdiction to search (EU, US, or ALL)",
    )
    parser.add_argument("--keyword", required=True, help="Search keyword or phrase")
    parser.add_argument(
        "--from",
        dest="from_date",
        default="2024-01-01",
        help="Start date YYYY-MM-DD (default: 2024-01-01)",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        default=datetime.utcnow().strftime("%Y-%m-%d"),
        help="End date YYYY-MM-DD (default: today)",
    )
    parser.add_argument("--limit", type=int, default=10, help="Max events per source")
    parser.add_argument(
        "--sources",
        default="",
        help="Comma-separated sources: eurlex,fr,sec (default: all)",
    )
    parser.add_argument("--out", default="", help="Write digest to file (optional)")
    parser.add_argument(
        "--ai", action="store_true",
        help="Use LLM-powered analysis (run_analysis). Default: direct fetch + keyword rules.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Resolve source aliases
    sources = None
    if args.sources:
        sources = []
        for alias in args.sources.split(","):
            alias = alias.strip().lower()
            resolved = SOURCE_ALIASES.get(alias)
            if resolved:
                sources.append(resolved)
            else:
                console.print(f"[red]Unknown source '{alias}'. Valid: eurlex, fr, sec[/red]")
                sys.exit(1)

    console.print(Rule("[bold blue]Policy Monitoring Agent[/bold blue]"))
    console.print(
        f"Jurisdiction: [bold]{args.jurisdiction}[/bold]  "
        f"Keyword: [bold]{args.keyword!r}[/bold]  "
        f"Range: {args.from_date} → {args.to_date}  "
        f"Limit: {args.limit}/source"
    )
    console.print()

    agent = PolicyMonitoringAgent()

    console.print("[dim]Fetching events…[/dim]")
    try:
        events = agent.query_updates(
            jurisdiction=args.jurisdiction,
            keyword=args.keyword,
            from_date=args.from_date,
            to_date=args.to_date,
            limit=args.limit,
            sources=sources,
        )
    except Exception as exc:
        console.print(f"[red]Error fetching events:[/red] {exc}")
        sys.exit(1)

    if not events:
        console.print("[yellow]No events found.[/yellow]")
        sys.exit(0)

    if args.ai:
        # ── TRUE AI AGENT mode ──────────────────────────────────────
        console.print("[dim]Running LLM-powered analysis…[/dim]\n")
        query = (
            f"Analyse policy and regulatory updates about '{args.keyword}' "
            f"in jurisdiction '{args.jurisdiction}' "
            f"from {args.from_date} to {args.to_date}. "
            f"Limit {args.limit} results per source."
            + (f" Only use sources: {', '.join(sources)}." if sources else "")
        )
        try:
            digest = agent.run_analysis(query)
        except Exception as exc:
            console.print(f"[red]LLM error:[/red] {exc}")
            sys.exit(1)
        console.print(Markdown(digest))
        console.print(Rule())
        if args.out:
            Path(args.out).write_text(digest, encoding="utf-8")
            console.print(f"\n[green]Saved to:[/green] {Path(args.out).resolve()}")
        return

    # ── PROGRAMMATIC mode (no LLM) ──────────────────────────────────
    console.print(f"Found [bold]{len(events)}[/bold] events. Generating digest…\n")

    digest = agent.generate_digest(
        events,
        title=f"Policy Digest — {args.keyword!r} ({args.from_date} → {args.to_date})",
    )

    # Display
    console.print(Markdown(digest))
    console.print(Rule())

    # Write to file
    if args.out:
        out_path = Path(args.out)
        out_path.write_text(digest, encoding="utf-8")
        console.print(f"\n[green]Digest saved to:[/green] {out_path.resolve()}")


if __name__ == "__main__":
    main()
