//! One Pulse job run, ported from pulse/runners/subprocess.py::execute. The timeout kills the whole
//! process GROUP: agent jobs are a bash wrapper over a php grandchild, and killing only the wrapper
//! (measured 2026-08-31) left the agent running and its lock slot leaked. Exit codes as Python's:
//! 126 refused, 127 not found, -9 timed out, -N killed by signal N, 255 any other spawn error.
use super::allow;
use std::io::Read;
use std::os::unix::process::{CommandExt, ExitStatusExt};
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

/// What wing_client.py posts: the last 2000 chars of each stream.
pub const TAIL_CHARS: usize = 2000;

#[derive(Debug)]
pub struct RunResult {
    pub exit_code: i32,
    pub duration_ms: u64,
    pub stdout_tail: String,
    pub stderr_tail: String,
    pub timed_out: bool,
}

/// Scrubbed WHOLE, then cut, as daemon.py then wing_client.py do: a cut first could drop the
/// `TOKEN=` a pattern needs and pass the value through.
fn tail(bytes: &[u8]) -> String {
    let s = super::redact::redact(&String::from_utf8_lossy(bytes));
    let skip = s.chars().count().saturating_sub(TAIL_CHARS);
    s.chars().skip(skip).collect()
}

// ponytail: each stream is held whole until EOF, as Python's communicate() does; a bounded ring if a job floods GBs.
fn drain(r: Option<impl Read + Send + 'static>, tx: mpsc::Sender<(bool, Vec<u8>)>, is_out: bool) {
    let mut r = r.expect("piped");
    std::thread::spawn(move || {
        let mut buf = Vec::new();
        let _ = r.read_to_end(&mut buf);
        let _ = tx.send((is_out, buf));
    });
}

pub fn execute(command: &str, args: &[String], env: &[(String, String)], timeout: Duration, home: Option<&str>, repo: Option<&str>) -> RunResult {
    let start = Instant::now();
    let done = |exit_code, out: &[u8], err: &[u8], timed_out| RunResult {
        exit_code, duration_ms: start.elapsed().as_millis() as u64, stdout_tail: tail(out), stderr_tail: tail(err), timed_out,
    };
    if let Err(e) = allow::validate(command, args, home, repo) {
        return done(126, b"", format!("pulse: command rejected by execution-boundary allowlist: {e}").as_bytes(), false);
    }
    let spawned = Command::new(command).args(args).env_clear().envs(env.iter().cloned())
        .stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped()).process_group(0).spawn();
    let mut child = match spawned {
        Ok(c) => c,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return done(127, b"", format!("command not found: '{command}' ({e})").as_bytes(), false),
        Err(e) => return done(255, b"", format!("daemon exception: {e}").as_bytes(), false),
    };
    let (tx, rx) = mpsc::channel();
    drain(child.stdout.take(), tx.clone(), true);
    drain(child.stderr.take(), tx, false);
    // Done = both pipes at EOF and the child reaped; a grandchild holding a pipe open keeps the run alive, as in Python.
    let (mut out, mut err, mut eofs, mut status) = (Vec::new(), Vec::new(), 0, None);
    let collect = |wait: Duration, out: &mut Vec<u8>, err: &mut Vec<u8>, eofs: &mut i32| {
        if let Ok((is_out, b)) = rx.recv_timeout(wait) {
            *if is_out { out } else { err } = b;
            *eofs += 1;
        }
    };
    let deadline = start + timeout;
    while eofs < 2 || status.is_none() {
        if Instant::now() >= deadline {
            // The pid is the group id (process_group(0)). ESRCH = the group is already gone: a race, not a failure.
            if unsafe { libc::killpg(child.id() as i32, libc::SIGKILL) } != 0 {
                let _ = child.kill();
            }
            let _ = child.wait();
            let bound = Instant::now() + Duration::from_secs(10); // a member that left the group may hold a pipe
            while eofs < 2 && Instant::now() < bound {
                collect(Duration::from_millis(50), &mut out, &mut err, &mut eofs);
            }
            return done(-9, &out, &err, true);
        }
        if eofs < 2 {
            collect(Duration::from_millis(20), &mut out, &mut err, &mut eofs);
        } else {
            std::thread::sleep(Duration::from_millis(5));
        }
        if status.is_none() {
            status = child.try_wait().ok().flatten();
        }
    }
    let s = status.expect("reaped");
    done(s.code().unwrap_or_else(|| -s.signal().unwrap_or(0)), &out, &err, false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    /// A temp repo whose tools/ holds `name` with `body`; dropped with the TempRepo.
    struct TempRepo(std::path::PathBuf);
    impl Drop for TempRepo {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
    fn repo(tag: &str, scripts: &[(&str, &str)]) -> TempRepo {
        let d = std::env::temp_dir().join(format!("medulla-exec-{tag}-{}", std::process::id()));
        std::fs::create_dir_all(d.join("tools")).unwrap();
        for (name, body) in scripts {
            let p = d.join("tools").join(name);
            std::fs::write(&p, format!("#!/bin/sh\n{body}\n")).unwrap();
            std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o755)).unwrap();
        }
        TempRepo(d)
    }
    fn run(r: &TempRepo, name: &str, env: &[(String, String)], timeout_ms: u64) -> RunResult {
        let cmd = r.0.join("tools").join(name);
        let path = [("PATH".to_string(), "/usr/bin:/bin".to_string())];
        let env = if env.is_empty() { &path[..] } else { env };
        execute(cmd.to_str().unwrap(), &[], env, Duration::from_millis(timeout_ms), None, r.0.to_str())
    }

    #[test]
    fn exit_codes_and_output() {
        let r = repo("codes", &[("ok", "echo hi; echo oops >&2"), ("three", "echo partial; exit 3"), ("sig", "kill -TERM $$")]);
        let ok = run(&r, "ok", &[], 2000);
        assert_eq!((ok.exit_code, ok.stdout_tail.as_str(), ok.stderr_tail.as_str(), ok.timed_out), (0, "hi\n", "oops\n", false));
        let three = run(&r, "three", &[], 2000);
        assert_eq!((three.exit_code, three.stdout_tail.as_str()), (3, "partial\n"));
        assert_eq!(run(&r, "sig", &[], 2000).exit_code, -15);
        let refused = execute("/etc/passwd", &[], &[], Duration::from_secs(1), None, r.0.to_str());
        assert_eq!(refused.exit_code, 126);
        assert!(refused.stderr_tail.starts_with("pulse: command rejected by execution-boundary allowlist: command path not in"), "{}", refused.stderr_tail);
        let missing = run(&r, "absent", &[], 2000);
        assert_eq!(missing.exit_code, 127);
        assert!(missing.stderr_tail.starts_with("command not found: '/"), "{}", missing.stderr_tail);
    }

    #[test]
    fn timeout_kills_the_grandchild_and_keeps_partial_output() {
        let r = repo("timeout", &[("slow", "echo before\nsleep 30 &\necho $! > \"$0.pid\"\nwait")]);
        let res = run(&r, "slow", &[], 1500);
        assert_eq!((res.exit_code, res.timed_out, res.stdout_tail.as_str()), (-9, true, "before\n"));
        assert!(res.duration_ms < 3000, "{}", res.duration_ms);
        let pid: i32 = std::fs::read_to_string(r.0.join("tools/slow.pid")).unwrap().trim().parse().unwrap();
        std::thread::sleep(Duration::from_millis(100));
        let alive = unsafe { libc::kill(pid, 0) } == 0;
        if alive {
            unsafe { libc::kill(pid, libc::SIGKILL) };
        }
        assert!(!alive, "grandchild {pid} survived the timeout");
    }

    #[test]
    fn a_megabyte_does_not_hang_and_the_tail_is_exact() {
        // 1 MB of digits, then a 3-byte char so a byte cut would split it, then a known end.
        let r = repo("flood", &[("flood", "yes 0123456789 | head -c 1048576; printf '\\342\\202\\254END'; yes e | head -c 1048576 >&2")]);
        let res = run(&r, "flood", &[], 2500);
        assert_eq!(res.exit_code, 0);
        let sent = "0123456789\n".repeat(95_326)[..1_048_576].to_string() + "\u{20ac}END";
        assert_eq!(res.stdout_tail, sent.chars().skip(sent.chars().count() - TAIL_CHARS).collect::<String>());
        assert_eq!(res.stderr_tail.chars().count(), TAIL_CHARS);
        let s = "ab\u{20ac}".repeat(1000); // 3000 chars, 5000 bytes
        assert_eq!(tail(s.as_bytes()), s.chars().skip(1000).collect::<String>(), "last 2000 chars, not bytes");
        assert_eq!(tail(b"ok\xff"), "ok\u{fffd}");
    }

    #[test]
    fn the_env_is_exactly_what_was_passed() {
        let r = repo("env", &[("showenv", "/usr/bin/env")]);
        let env = [("PULSE_RUN_ID".to_string(), "r1".to_string())];
        let res = run(&r, "showenv", &env, 2000);
        // Failed once in ~15 full runs (2026-10-25, not reproduced): say how, next time.
        assert!(res.exit_code == 0 && !res.timed_out, "{res:?}");
        let mut keys: Vec<&str> = res.stdout_tail.lines().map(|l| l.split('=').next().unwrap()).collect();
        keys.retain(|k| *k != "PWD" && *k != "SHLVL" && *k != "_"); // /bin/sh adds these itself
        assert_eq!(keys, ["PULSE_RUN_ID"], "{}", res.stdout_tail);
    }
}
