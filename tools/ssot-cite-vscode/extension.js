/* nOS SSOT cites — spawn doctrine-cite.py --file; do not parse cites here. */
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const vscode = require("vscode");

// wrong / missing-doc / unknown-id → Error; moved → Warning; unqualified → Information
const SEVERITY = {
  wrong: vscode.DiagnosticSeverity.Error,
  "missing-doc": vscode.DiagnosticSeverity.Error,
  "unknown-id": vscode.DiagnosticSeverity.Error,
  moved: vscode.DiagnosticSeverity.Warning,
  unqualified: vscode.DiagnosticSeverity.Information,
};

const cache = new Map(); // fsPath -> { citations }
let diags;
let spawnTold;

function repoRoot(start) {
  let dir = start;
  for (let i = 0; i < 10; i++) {
    if (
      fs.existsSync(path.join(dir, "ssot", "INDEX.yml")) &&
      fs.existsSync(path.join(dir, "tools", "doctrine-cite.py"))
    ) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

function runFile(root, rel) {
  return new Promise((resolve, reject) => {
    const script = path.join(root, "tools", "doctrine-cite.py");
    const child = spawn("python3", [script, "--file", rel, "--json"], {
      cwd: root,
    });
    let out = "";
    let err = "";
    const t = setTimeout(() => {
      child.kill();
      reject(new Error("doctrine-cite.py --file timed out"));
    }, 10000);
    child.stdout.on("data", (d) => {
      out += d;
    });
    child.stderr.on("data", (d) => {
      err += d;
    });
    child.on("error", (e) => {
      clearTimeout(t);
      reject(e);
    });
    child.on("close", (code) => {
      clearTimeout(t);
      if (code !== 0) {
        reject(new Error(err.trim() || `doctrine-cite.py exit ${code}`));
        return;
      }
      try {
        resolve(JSON.parse(out));
      } catch (e) {
        reject(e);
      }
    });
  });
}

async function refresh(doc) {
  if (doc.uri.scheme !== "file") return;
  const root = repoRoot(path.dirname(doc.uri.fsPath));
  if (!root) return;
  const rel = path.relative(root, doc.uri.fsPath).split(path.sep).join("/");
  if (!rel || rel.startsWith("..")) return;
  try {
    const data = await runFile(root, rel);
    const citations = (data.citations || []).filter((c) => c.shape === "section");
    cache.set(doc.uri.fsPath, { root, citations });
    const items = [];
    for (const c of citations) {
      if (c.lint === false) continue;
      const sev = SEVERITY[c.status];
      if (sev === undefined) continue;
      const range = new vscode.Range(
        c.line - 1,
        c.col || 0,
        c.line - 1,
        Math.max(c.end_col || 0, (c.col || 0) + 1),
      );
      items.push(new vscode.Diagnostic(range, `${c.status} ${c.key}`, sev));
    }
    diags.set(doc.uri, items);
  } catch (e) {
    cache.delete(doc.uri.fsPath);
    diags.delete(doc.uri);
    if (!spawnTold) {
      spawnTold = true;
      vscode.window.showInformationMessage(
        `nOS SSOT cites: ${e.message || e}`,
      );
    }
  }
}

function targetUri(root, c) {
  if (!c.doc) return null;
  const file = path.join(root, c.doc);
  const line = Math.max((c.target_line || 1) - 1, 0);
  return vscode.Uri.file(file).with({ fragment: `L${line + 1}` });
}

function activate(context) {
  diags = vscode.languages.createDiagnosticCollection("nos-ssot-cite");
  context.subscriptions.push(diags);

  const selector = { scheme: "file" };

  context.subscriptions.push(
    vscode.languages.registerDocumentLinkProvider(selector, {
      provideDocumentLinks(doc) {
        const hit = cache.get(doc.uri.fsPath);
        if (!hit) return [];
        const links = [];
        for (const c of hit.citations) {
          const uri = targetUri(hit.root, c);
          if (!uri) continue;
          const range = new vscode.Range(
            c.line - 1,
            c.col || 0,
            c.line - 1,
            Math.max(c.end_col || 0, (c.col || 0) + 1),
          );
          const link = new vscode.DocumentLink(range, uri);
          links.push(link);
        }
        return links;
      },
    }),
    vscode.languages.registerDefinitionProvider(selector, {
      provideDefinition(doc, pos) {
        const hit = cache.get(doc.uri.fsPath);
        if (!hit) return [];
        for (const c of hit.citations) {
          if (pos.line !== c.line - 1) continue;
          if (pos.character < (c.col || 0) || pos.character > (c.end_col || 0)) {
            continue;
          }
          if (!c.doc) continue;
          const loc = new vscode.Location(
            vscode.Uri.file(path.join(hit.root, c.doc)),
            new vscode.Position(Math.max((c.target_line || 1) - 1, 0), 0),
          );
          return [loc];
        }
        return [];
      },
    }),
    vscode.languages.registerHoverProvider(selector, {
      provideHover(doc, pos) {
        const hit = cache.get(doc.uri.fsPath);
        if (!hit) return null;
        for (const c of hit.citations) {
          if (pos.line !== c.line - 1) continue;
          if (pos.character < (c.col || 0) || pos.character > (c.end_col || 0)) {
            continue;
          }
          if (!c.excerpt) return null;
          return new vscode.Hover(new vscode.MarkdownString(c.excerpt));
        }
        return null;
      },
    }),
    vscode.workspace.onDidOpenTextDocument(refresh),
    vscode.workspace.onDidSaveTextDocument(refresh),
  );
  vscode.workspace.textDocuments.forEach(refresh);
}

function deactivate() {
  cache.clear();
}

module.exports = { activate, deactivate };
