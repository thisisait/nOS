//! Pulse's stdout/stderr scrub, a port of pulse/redact.py scrub_text: six patterns in its order,
//! each keeps the labelled prefix and puts <REDACTED> where the value was. No regex crate: each
//! pattern is a matcher tried at every char, like re.sub. tests/fixtures/pulse_redact.json holds the
//! pairs both suites must produce, generated from the Python.

const R: &str = "<REDACTED>";

/// Python's `\s` on str: Unicode White_Space plus U+001C..U+001F.
fn space(c: char) -> bool {
    c.is_whitespace() || ('\x1c'..='\x1f').contains(&c)
}

// ponytail: Rust's Alphabetic vs Python's isalnum for `\w`; they part on some combining marks.
fn word(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

/// re.IGNORECASE folds four non-ASCII letters onto ASCII ones (Kelvin sign, long s, dotted/dotless i).
fn fold(c: char) -> char {
    match c {
        '\u{212a}' => 'K',
        '\u{17f}' => 'S',
        '\u{130}' | '\u{131}' => 'I',
        c => c.to_ascii_uppercase(),
    }
}

fn boundary(t: &[char], i: usize) -> bool {
    (i > 0 && word(t[i - 1])) != (i < t.len() && word(t[i]))
}

fn value(c: char) -> bool {
    c.is_ascii_alphanumeric() || "+/=_.-".contains(c)
}

fn run(t: &[char], i: usize, max: usize, ok: impl Fn(char) -> bool) -> usize {
    t[i.min(t.len())..].iter().take(max).take_while(|c| ok(**c)).count()
}

fn spaces(t: &[char], i: usize) -> usize {
    i + run(t, i, usize::MAX, space)
}

/// `kw` (upper-case ASCII) at `i`, case folded.
fn lit(t: &[char], i: usize, kw: &str) -> bool {
    t.len() >= i + kw.len() && kw.chars().zip(&t[i..]).all(|(k, c)| fold(*c) == k)
}

fn first<'a>(t: &[char], i: usize, kws: &[&'a str]) -> Option<&'a str> {
    kws.iter().copied().find(|k| lit(t, i, k))
}

fn quoted(t: &[char], i: usize, min: usize) -> Option<usize> {
    let q = *t.get(i).filter(|c| matches!(c, '\'' | '"'))?;
    let n = run(t, i + 1, usize::MAX, |c| c != q && c != '\n');
    (n >= min && t.get(i + 1 + n) == Some(&q)).then_some(i + n + 2)
}

/// Python's _ENV_ASSIGNMENT: a long keyword anywhere in the key, KEY/AUTH ending a `_` segment
/// (KEY not after MON or SORT_); then `"…"`/`'…'`, or for `:` the rest of the line, for `=` a
/// `['"]?[^\s'"]{6,}['"]?` run.
fn env(t: &[char], p: usize) -> Option<(usize, usize)> {
    const KW: [&str; 10] = ["TOKEN", "SECRET", "PASSWORD", "PASSWD", "APIKEY", "HMAC", "JWT", "BEARER", "CREDENTIAL", "COOKIE"];
    if !boundary(t, p) || !fold(t[p]).is_ascii_uppercase() {
        return None;
    }
    let r = p + run(t, p, usize::MAX, |c| matches!(fold(c), 'A'..='Z' | '0'..='9' | '_'));
    let seg = |k: usize, kw: &str| {
        !(kw == "KEY" && (k >= 3 && lit(t, k - 3, "MON") || k >= 5 && lit(t, k - 5, "SORT_")))
            && (k + kw.len() == r || t.get(k + kw.len()) == Some(&'_'))
    };
    (p..r).find(|&k| {
        KW.iter().any(|kw| k + kw.len() <= r && lit(t, k, kw)) || ["KEY", "AUTH"].iter().any(|kw| k + kw.len() <= r && lit(t, k, kw) && seg(k, kw))
    })?;
    let j = spaces(t, r);
    let colon = match t.get(j) {
        Some(':') => true,
        Some('=') => false,
        _ => return None,
    };
    let keep = spaces(t, j + 1);
    if let Some(end) = quoted(t, keep, 6) {
        return Some((keep, end));
    }
    if colon {
        let n = run(t, keep, usize::MAX, |c| c != '\n');
        return (n >= 6).then_some((keep, keep + n));
    }
    let quote = |i: usize| matches!(t.get(i), Some('\'' | '"')) as usize;
    let q = keep + quote(keep);
    let n = run(t, q, usize::MAX, |c| !space(c) && c != '\'' && c != '"');
    (n >= 6).then(|| (keep, q + n + quote(q + n)))
}

/// `--?(?:password|passwd|pass|pwd|token|secret|api[-_]?key|bearer)[ =]` then a quoted value or `[^\s]+`, IGNORECASE.
fn cli(t: &[char], p: usize) -> Option<(usize, usize)> {
    if t[p] != '-' {
        return None;
    }
    let k = p + 1 + (t.get(p + 1) == Some(&'-')) as usize;
    const KW: [&str; 10] = ["PASSWORD", "PASSWD", "PASS", "PWD", "TOKEN", "SECRET", "API-KEY", "API_KEY", "APIKEY", "BEARER"];
    KW.iter().filter(|kw| lit(t, k, kw)).find_map(|kw| {
        let s = k + kw.len() + 1;
        if !matches!(t.get(s - 1), Some(' ' | '=')) {
            return None;
        }
        let n = run(t, s, usize::MAX, |c| !space(c));
        quoted(t, s, 0).or((n > 0).then_some(s + n)).map(|end| (s, end))
    })
}

/// `Authorization\s*:\s*(?:Bearer|Basic|Digest|Token)\s+[value]{8,}`, IGNORECASE.
fn http(t: &[char], p: usize) -> Option<(usize, usize)> {
    if !lit(t, p, "AUTHORIZATION") {
        return None;
    }
    let j = spaces(t, p + 13);
    if t.get(j) != Some(&':') {
        return None;
    }
    let j = spaces(t, j + 1);
    let s = j + first(t, j, &["BEARER", "BASIC", "DIGEST", "TOKEN"])?.len();
    let keep = spaces(t, s);
    let n = run(t, keep, usize::MAX, |c| value(fold(c)));
    (keep > s && n >= 8).then_some((keep, keep + n))
}

/// `\bBearer\s+[value]{16,}\b`, IGNORECASE; the trailing `\b` backtracks the value.
fn bearer(t: &[char], p: usize) -> Option<(usize, usize)> {
    if !boundary(t, p) || !lit(t, p, "BEARER") {
        return None;
    }
    let keep = spaces(t, p + 6);
    let n = run(t, keep, usize::MAX, |c| value(fold(c)));
    (keep > p + 6).then_some(())?;
    (16..=n).rev().find(|l| boundary(t, keep + l)).map(|l| (keep, keep + l))
}

/// Case-sensitive literal at `p` (the bare-token prefixes are case-sensitive in the Python).
fn exact(t: &[char], p: usize, s: &str) -> bool {
    let n = s.chars().count();
    p + n <= t.len() && t[p..p + n].iter().copied().eq(s.chars())
}

/// `[A-Za-z0-9_\-]`: a token character (ASCII only, as the Python class).
fn tok(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '_' || c == '-'
}

/// `(?<![A-Za-z0-9_])(gh[pousr]_|github_pat_|xox[abprs]-|sk-ant-|sk-|AKIA)[tok]{16,}`; the
/// alternatives are tried in that order, as re's alternation is.
fn bare(t: &[char], p: usize) -> Option<(usize, usize)> {
    if p > 0 && (t[p - 1].is_ascii_alphanumeric() || t[p - 1] == '_') {
        return None;
    }
    const PREFIXES: [&str; 14] = ["ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_", "xoxa-", "xoxb-", "xoxp-",
                                  "xoxr-", "xoxs-", "sk-ant-", "sk-", "AKIA"];
    let pre = PREFIXES.iter().find(|s| exact(t, p, s))?;
    let keep = p + pre.chars().count();
    let n = run(t, keep, usize::MAX, tok);
    (n >= 16).then_some((keep, keep + n))
}

/// `(?<![tok])eyJ[tok]{8,}\.[tok]{8,}\.[tok]{8,}`: a JWT; `.` is not a token char, so each greedy
/// segment run is the regex's own.
fn jwt(t: &[char], p: usize) -> Option<(usize, usize)> {
    if (p > 0 && tok(t[p - 1])) || !exact(t, p, "eyJ") {
        return None;
    }
    let keep = p + 3;
    let mut j = keep;
    for seg in 0..3 {
        let n = run(t, j, usize::MAX, tok);
        if n < 8 {
            return None;
        }
        j += n;
        if seg < 2 {
            if t.get(j) != Some(&'.') {
                return None;
            }
            j += 1;
        }
    }
    Some((keep, j))
}

fn sub(t: Vec<char>, m: fn(&[char], usize) -> Option<(usize, usize)>) -> Vec<char> {
    let (mut out, mut i) = (Vec::with_capacity(t.len()), 0);
    while i < t.len() {
        match m(&t, i) {
            Some((keep, end)) => {
                out.extend_from_slice(&t[i..keep]);
                out.extend(R.chars());
                i = end;
            }
            None => {
                out.push(t[i]);
                i += 1;
            }
        }
    }
    out
}

pub fn redact(text: &str) -> String {
    [env, cli, http, bearer, bare, jwt].into_iter().fold(text.chars().collect(), sub).into_iter().collect()
}

#[cfg(test)]
mod tests {
    /// The pairs test_pulse_redact runs through the Python scrub_text, from one file.
    #[test]
    fn the_shared_pairs() {
        let v: serde_json::Value = serde_json::from_str(include_str!("../../../../../../tests/fixtures/pulse_redact.json")).unwrap();
        let pairs = v["pairs"].as_array().unwrap();
        let bad: Vec<String> = pairs
            .iter()
            .filter_map(|p| {
                let (input, want) = (p[0].as_str().unwrap(), p[1].as_str().unwrap());
                let got = super::redact(input);
                (got != want).then(|| format!("{input:?}\n   want {want:?}\n    got {got:?}"))
            })
            .collect();
        assert!(bad.is_empty(), "{} of {} pairs differ:\n{}", bad.len(), pairs.len(), bad.join("\n"));
    }
}
