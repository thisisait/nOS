//! The Pulse command allowlist, third copy: PulsePresenter::validatePulseCommand checks at registration,
//! pulse/runners/subprocess.py::validate_command at exec, this before the medulla fires.
//! test_pulse_command_allowlist pins the constants and the vectors on all three.
pub const SYSTEM_BINARIES: &[&str] = &["/opt/homebrew/bin/php"];
pub const HOME_BINARIES: &[&str] = &[".local/bin/frankenphp"];
pub const REPO_TREES: &[&str] = &["tools/", "files/anatomy/scripts/", "files/anatomy/plugins/", "files/vuln-scan/"];
pub const HOME_TREES: &[&str] = &["wing/", ".nos/"];
pub const INTERPRETERS: &[&str] = &["php", "frankenphp", "node", "ruby", "perl"]; // + python[0-9.]*
pub const BANNED_BASENAMES: &[&str] = &[
    "bash", "bun", "bunx", "csh", "dash", "docker", "env", "fish", "gtimeout", "ksh", "nohup", "npm", "npx", "pip",
    "pip3", "sh", "su", "sudo", "timeout", "uv", "uvx", "xargs", "zsh",
];

/// `HOME` / `NOS_REPO_ROOT` as a tree root: absolute, one trailing slash; anything else roots nothing.
fn root(v: Option<&str>) -> String {
    let v = v.unwrap_or("").trim_end_matches('/');
    if v.starts_with('/') { format!("{v}/") } else { String::new() }
}

fn dotted(p: &str) -> bool {
    format!("{p}/").contains("/../") || p.contains("/./")
}

fn interpreter(b: &str) -> bool {
    INTERPRETERS.contains(&b) || b.strip_prefix("python").is_some_and(|r| r.chars().all(|c| c.is_ascii_digit() || c == '.'))
}

// ponytail: strict where PHP's and Python's `$` also accept one trailing newline; refusing more is the safe side.
fn basename_ok(b: &str) -> bool {
    let mut c = b.chars();
    c.next().is_some_and(|f| f.is_ascii_lowercase())
        && b.len() <= 64
        && c.all(|x| x.is_ascii_alphanumeric() || "._-".contains(x))
}

fn arg_ok(a: &str) -> bool {
    a.len() <= 512 && a.chars().all(|x| x.is_ascii_alphanumeric() || "._@/:=,+~-".contains(x))
}

/// Err names the first rule the command breaks, in the order the other two check them.
pub fn validate(command: &str, args: &[String], home: Option<&str>, repo: Option<&str>) -> Result<(), String> {
    let (home, repo) = (root(home), root(repo));
    let trees: Vec<String> = REPO_TREES.iter().filter(|_| !repo.is_empty()).map(|t| format!("{repo}{t}"))
        .chain(HOME_TREES.iter().filter(|_| !home.is_empty()).map(|t| format!("{home}{t}")))
        .collect();
    let in_trees = |p: &str| trees.iter().any(|t| p.starts_with(t.as_str()));
    if !command.starts_with('/') {
        return Err("command must be an absolute path".into());
    }
    if dotted(command) {
        return Err("command path must be normalised (no . or .. segments)".into());
    }
    let named = SYSTEM_BINARIES.contains(&command) || (!home.is_empty() && HOME_BINARIES.iter().any(|b| format!("{home}{b}") == command));
    if !named && !in_trees(command) {
        return Err("command path not in Pulse allowlist".into());
    }
    let base = command.rsplit('/').next().unwrap_or("");
    if BANNED_BASENAMES.contains(&base) {
        return Err(format!("command basename '{base}' is banned (shell or exec wrapper)"));
    }
    if !basename_ok(base) {
        return Err("command basename malformed".into());
    }
    if let Some(i) = args.iter().position(|a| !arg_ok(a)) {
        return Err(format!("args[{i}] contains banned characters"));
    }
    if interpreter(base) {
        let script = args.iter().find(|a| *a != "php-cli").map(String::as_str).unwrap_or("");
        if dotted(script) || !in_trees(script) {
            return Err(format!("{base} must run a script from the Pulse trees, got '{script}'"));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    /// The cases test_pulse_command_allowlist runs against the Python runner, from one file.
    #[test]
    fn the_shared_cases() {
        let v: serde_json::Value = serde_json::from_str(include_str!("../../../../../../tests/fixtures/pulse_allow.json")).unwrap();
        let (home, repo) = (v["home"].as_str(), v["repo"].as_str());
        let case = |c: &serde_json::Value| -> (String, Vec<String>) {
            let args = c[1].as_array().unwrap().iter().map(|a| a.as_str().unwrap().to_string()).collect();
            (c[0].as_str().unwrap().to_string(), args)
        };
        for c in v["refused"].as_array().unwrap() {
            let (cmd, args) = case(c);
            assert!(super::validate(&cmd, &args, home, repo).is_err(), "allowed: {cmd} {args:?}");
        }
        for c in v["allowed"].as_array().unwrap() {
            let (cmd, args) = case(c);
            assert_eq!(super::validate(&cmd, &args, home, repo), Ok(()), "{cmd} {args:?}");
        }
        for bad in [Some("/"), Some(""), None] {
            assert!(super::validate("/etc/evil", &[], bad, None).is_err());
        }
    }
}
