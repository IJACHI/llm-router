# ijachi-code for VS Code

Runs the `ijachi-code` agent in VS Code's integrated terminal, so the editor and CLI share one
session store, routing configuration and permission rules.

| Command | Default key | What it does |
|---|---|---|
| ijachi: Open Agent | ⌘⌥I / Ctrl+Alt+I | Opens (or focuses) the agent terminal in the workspace |
| ijachi: Ask About Selection | ⌘⌥K / Ctrl+Alt+K | Sends `@file (lines a-b) <question>` to the agent |
| ijachi: Fix Problems in This File | editor menu | Sends the file's errors/warnings from VS Code diagnostics |
| ijachi: New Task in Isolated Worktree | — | Starts `ijachi-code --worktree <name> "<task>"` in a new terminal |

Install locally: `cd editors/vscode && npx @vscode/vsce package` then *Extensions → … → Install from VSIX*.
Settings: `ijachi.command` (path to the CLI) and `ijachi.extraArgs` (e.g. `--mode cheapest`).
