//! Pulse's stdout/stderr scrub, a port of pulse/redact.py scrub_text: four patterns in its order,
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

/// `\b[A-Z][A-Z0-9_]*(?:TOKEN|…)[A-Z0-9_]*\s*[:=]\s*['"]?[value]{6,256}['"]?`, IGNORECASE.
fn env(t: &[char], p: usize) -> Option<(usize, usize)> {
    const KW: [&str; 10] = ["TOKEN", "SECRET", "PASSWORD", "KEY", "HMAC", "JWT", "BEARER", "CREDENTIAL", "AUTH", "COOKIE"];
    if !boundary(t, p) || !fold(t[p]).is_ascii_uppercase() {
        return None;
    }
    let r = p + run(t, p, usize::MAX, |c| matches!(fold(c), 'A'..='Z' | '0'..='9' | '_'));
    (p + 1..r).find(|&k| KW.iter().any(|kw| k + kw.len() <= r && lit(t, k, kw)))?;
    let j = spaces(t, r);
    if !matches!(t.get(j), Some(':' | '=')) {
        return None;
    }
    let keep = spaces(t, j + 1);
    let q = keep + matches!(t.get(keep), Some('\'' | '"')) as usize;
    let n = run(t, q, 256, |c| value(fold(c)));
    (n >= 6).then(|| (keep, q + n + matches!(t.get(q + n), Some('\'' | '"')) as usize))
}

/// `--?(?:password|pass|pwd|token|secret|api[-_]?key|bearer)[ =]` then `[^\s]+`, IGNORECASE.
fn cli(t: &[char], p: usize) -> Option<(usize, usize)> {
    if t[p] != '-' {
        return None;
    }
    let k = p + 1 + (t.get(p + 1) == Some(&'-')) as usize;
    const KW: [&str; 9] = ["PASSWORD", "PASS", "PWD", "TOKEN", "SECRET", "API-KEY", "API_KEY", "APIKEY", "BEARER"];
    KW.iter().filter(|kw| lit(t, k, kw)).find_map(|kw| {
        let s = k + kw.len() + 1;
        let n = run(t, s, usize::MAX, |c| !space(c));
        (matches!(t.get(s - 1), Some(' ' | '=')) && n > 0).then_some((s, s + n))
    })
}

/// `Authorization\s*:\s*(?:Bearer|Basic|Digest)\s+[value]{8,512}`, IGNORECASE.
fn http(t: &[char], p: usize) -> Option<(usize, usize)> {
    if !lit(t, p, "AUTHORIZATION") {
        return None;
    }
    let j = spaces(t, p + 13);
    if t.get(j) != Some(&':') {
        return None;
    }
    let j = spaces(t, j + 1);
    let s = j + first(t, j, &["BEARER", "BASIC", "DIGEST"])?.len();
    let keep = spaces(t, s);
    let n = run(t, keep, 512, |c| value(fold(c)));
    (keep > s && n >= 8).then_some((keep, keep + n))
}

/// `\bBearer\s+[value]{16,512}\b`, case-sensitive; the trailing `\b` backtracks the value.
fn bearer(t: &[char], p: usize) -> Option<(usize, usize)> {
    if !boundary(t, p) || !t[p..].starts_with(&['B', 'e', 'a', 'r', 'e', 'r']) {
        return None;
    }
    let keep = spaces(t, p + 6);
    let n = run(t, keep, 512, value);
    (keep > p + 6).then_some(())?;
    (16..=n).rev().find(|l| boundary(t, keep + l)).map(|l| (keep, keep + l))
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
    [env, cli, http, bearer].into_iter().fold(text.chars().collect(), sub).into_iter().collect()
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
