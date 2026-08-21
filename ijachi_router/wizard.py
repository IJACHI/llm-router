"""Interactive Welcome Launcher & Multi-Provider Key Setup Wizard for ijachi-code.

Displays compatible LLM service providers, checks key status, allows multi-key entry,
and configures provider sessions dynamically.
"""

from __future__ import annotations

import os
from typing import Any
from rich.console import Console
from rich.prompt import Prompt, Confirm

from ijachi_router.key_manager import KeyManager, _PROVIDER_ENV_VARS

console = Console()

_PROVIDER_DESCRIPTIONS = {
    "anthropic": "Claude 3.7 Sonnet, Claude 3.5 Haiku (Enterprise Reasoning & Coding)",
    "openai": "GPT-4o, GPT-4o-mini (General QA, Coding, Math)",
    "gemini": "Gemini 2.5 Flash, Gemini 2.5 Pro (Google High-Speed Multimodal)",
    "deepseek": "DeepSeek V3, DeepSeek R1 Reasoner (Low-Cost Frontier Reasoning)",
    "groq": "Llama 3.3 70B (Ultra-Fast LPU Inference)",
    "cerebras": "Llama 3.1 70B (Ultra-Fast 1800+ tok/s Inference)",
    "local": "Local Ollama Models (100% Free Offline Coding)",
    "qwen": "Qwen-Max, Qwen-2.5-Coder (Alibaba Cloud)",
    "moonshot": "Kimi Latest (Long Context Reasoning)",
    "perplexity": "Sonar Pro (Web-Grounded Search Reasoning)",
    "cohere": "Command R+ (Enterprise Reasoning & RAG)",
    "huggingface": "HF Hosted Inference Models",
    "fireworks": "Fireworks Fast Llama 3.1",
    "sambanova": "SambaNova Meta-Llama 405B",
    "bedrock": "AWS Bedrock Hosted Models",
    "azure": "Azure OpenAI Enterprise Models",
}


class LauncherWizard:
    """Manages the interactive welcome screen and multi-provider key configuration."""

    def __init__(self):
        self.km = KeyManager()
        self.km.load_keys_into_env()

    def get_provider_status(self) -> dict[str, dict[str, Any]]:
        """Returns map of provider -> {env_var, active, description}."""
        status = {}
        for p, env_var in _PROVIDER_ENV_VARS.items():
            if p == "local":
                is_active = True  # Ollama always available locally
            else:
                is_active = bool(os.getenv(env_var))
            status[p] = {
                "env_var": env_var,
                "active": is_active,
                "description": _PROVIDER_DESCRIPTIONS.get(p, "LLM Service Provider"),
            }
        return status

    @staticmethod
    def print_welcome_table() -> None:
        """Render clean terminal table of all compatible providers and key status."""
        from rich.table import Table
        from rich.panel import Panel
        from ijachi_router.ui import print_banner, get_status_pill, get_badge

        print_banner()

        table = Table(title="[bold gold1]⚡ Supported LLM Service Providers & Status[/bold gold1]", border_style="bright_blue", header_style="bold magenta")
        table.add_column("Provider", style="bold cyan", width=15)
        table.add_column("Status Badge", width=18)
        table.add_column("Env Variable", style="dim white", width=22)
        table.add_column("Model Capability & Best Use", style="italic white", width=45)

        status_map = LauncherWizard().get_provider_status()

        for p, info in status_map.items():
            is_free = (p == "local")
            pill = get_status_pill(active=info["active"], is_free=is_free)
            table.add_row(p.upper(), pill, info["env_var"], info["description"])

        console.print(Panel(table, border_style="cyan", padding=(1, 1)))
        console.print("\n[dim cyan]💡 Tip: You can configure multiple provider API keys. ijachi-code automatically switches and falls back if a provider is down.[/dim cyan]\n")

    def run_interactive_setup(self) -> None:
        """Interactive setup flow for selecting providers and entering API keys."""
        self.print_welcome_table()

        # Check whether any remote provider is already configured
        status = self.get_provider_status()
        remote_active = [p for p, info in status.items() if p != "local" and info["active"]]

        if not Confirm.ask("Would you like to configure or add provider API keys now?", default=not bool(remote_active)):
            if remote_active:
                console.print(f"[green]✓ Ready to proceed with active providers: {', '.join(remote_active)}[/green]")
            else:
                console.print(
                    "\n[bold yellow]⚠ No remote providers configured.[/bold yellow]\n"
                    "  You can still use the [bold]local[/bold] Ollama provider (if running).\n"
                    "  To add a provider key later, run: [bold cyan]ijachi keys set <provider> <key>[/bold cyan]\n"
                )
            return

        while True:
            provider_input = Prompt.ask("\nEnter provider name to configure (e.g. anthropic, openai, groq, deepseek) or 'done'")
            provider = provider_input.strip().lower()

            if provider in {"done", "exit", "quit", ""}:
                break

            if provider not in _PROVIDER_ENV_VARS and provider != "local":
                console.print(f"[bold red]Unknown provider '{provider}'.[/bold red] Choose from: {', '.join(list(_PROVIDER_ENV_VARS.keys())[:8])}")
                continue

            if provider == "local":
                console.print("[dim]Local Ollama provider needs no API key — it's always available when Ollama is running.[/dim]")
                continue

            existing_key = self.km.get_key(provider)
            if existing_key:
                console.print(f"Existing key found for [cyan]{provider}[/cyan]: [dim]{existing_key[:6]}***[/dim]")
                if not Confirm.ask(f"Do you want to overwrite the key for {provider}?", default=False):
                    continue

            key_val = Prompt.ask(f"Enter API key for [cyan]{provider}[/cyan]", password=True)
            if key_val.strip():
                msg = self.km.set_key(provider, key_val.strip())
                # Immediately activate key in current process environment
                self.km.load_keys_into_env()
                console.print(f"[bold green]✓ {msg}[/bold green]")

        # Reload all saved keys so they're active in this process for the chat session
        self.km.load_keys_into_env()
        console.print("\n[bold green]✓ Key configuration complete! All selected providers are active for your session.[/bold green]\n")

