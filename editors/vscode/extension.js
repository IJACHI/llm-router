// ijachi-code VS Code integration: drives the ijachi-code CLI in an integrated terminal,
// so the editor and the terminal share one agent loop, session store and permission rules.
const vscode = require("vscode");
const path = require("path");

let agentTerminal = null;

function config() {
  const c = vscode.workspace.getConfiguration("ijachi");
  return { command: c.get("command") || "ijachi-code", extraArgs: c.get("extraArgs") || "" };
}

function workspaceRoot(uri) {
  const folder = (uri && vscode.workspace.getWorkspaceFolder(uri)) || (vscode.workspace.workspaceFolders || [])[0];
  return folder ? folder.uri.fsPath : undefined;
}

function shellQuote(s) {
  return "'" + String(s).replace(/'/g, "'\\''") + "'";
}

function ensureAgent(cwd) {
  if (agentTerminal && agentTerminal.exitStatus === undefined) {
    agentTerminal.show(true);
    return agentTerminal;
  }
  const { command, extraArgs } = config();
  agentTerminal = vscode.window.createTerminal({ name: "ijachi-code", cwd });
  agentTerminal.sendText(`${command} ${extraArgs}`.trim());
  agentTerminal.show(true);
  return agentTerminal;
}

function relPath(editor) {
  const root = workspaceRoot(editor.document.uri);
  return root ? path.relative(root, editor.document.uri.fsPath) : editor.document.uri.fsPath;
}

// The REPL treats a newline-free line as one message; flatten multi-line text.
function oneLine(text) {
  return text.replace(/\r?\n/g, " \\n ").slice(0, 6000);
}

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("ijachi.open", () => {
      const editor = vscode.window.activeTextEditor;
      ensureAgent(workspaceRoot(editor && editor.document.uri));
    }),

    vscode.commands.registerCommand("ijachi.askSelection", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) return;
      const sel = editor.selection;
      const question = await vscode.window.showInputBox({ prompt: "Ask ijachi about the selection", placeHolder: "Explain this / refactor it / why does it fail?" });
      if (!question) return;
      const rel = relPath(editor);
      const lines = `lines ${sel.start.line + 1}-${sel.end.line + 1}`;
      const term = ensureAgent(workspaceRoot(editor.document.uri));
      term.sendText(oneLine(`@${rel} (${lines}) ${question}`));
    }),

    vscode.commands.registerCommand("ijachi.fixProblems", () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) return;
      const diags = vscode.languages.getDiagnostics(editor.document.uri)
        .filter((d) => d.severity <= vscode.DiagnosticSeverity.Warning)
        .slice(0, 30)
        .map((d) => `line ${d.range.start.line + 1}: ${d.message}`);
      if (!diags.length) {
        vscode.window.showInformationMessage("ijachi: no errors or warnings in this file.");
        return;
      }
      const rel = relPath(editor);
      const term = ensureAgent(workspaceRoot(editor.document.uri));
      term.sendText(oneLine(`Fix these problems in @${rel}: ${diags.join("; ")}`));
    }),

    vscode.commands.registerCommand("ijachi.newTask", async () => {
      const task = await vscode.window.showInputBox({ prompt: "Describe the task (runs on its own branch + worktree)" });
      if (!task) return;
      const { command, extraArgs } = config();
      const name = task.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "task";
      const term = vscode.window.createTerminal({ name: `ijachi: ${name}`, cwd: workspaceRoot() });
      term.sendText(`${command} ${extraArgs} --worktree ${shellQuote(name)} ${shellQuote(task)}`.replace(/\s+/g, " ").trim());
      term.show(true);
    }),
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
