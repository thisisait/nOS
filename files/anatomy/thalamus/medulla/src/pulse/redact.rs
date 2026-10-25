//! Pulse's stdout/stderr scrub: files/anatomy/contracts/redact.yml as code, the same algorithm as
//! pulse/redact.py scrub_text step for step. No regex crate: each layer is a matcher tried at
//! every char. contracts/redact.fixture.json holds the answers both must give.

const R: &str = "<REDACTED>";
const STRONG: &[&str] = &["TOKEN", "SECRET", "PASSWORD", "PASSWD", "APIKEY", "HMAC", "JWT", "CREDENTIAL", "CREDENTIALS", "PASSPHRASE"];
const WEAK: &[&str] = &["PASS", "PWD", "KEY", "AUTH", "BEARER", "COOKIE"];
const BENIGN_KEYS: &[&str] = &["SORT_KEY", "PRIMARY_KEY", "FOREIGN_KEY", "TAIL_KEY"];
const BENIGN_TAILS: &[&str] = &["NAME", "TYPE", "FILE", "PATH", "URL", "ERROR", "EXCEPTION"];
const FLAGS: &[&str] = &["password", "passwd", "api-key", "api_key", "apikey", "secret", "bearer", "token", "pass", "pwd"];
const SCHEMES: &[&str] = &["bearer", "basic", "digest", "token", "apikey"];
const BEARER_MIN: usize = 16;
const KNOWN_MIN: usize = 6;

type Hit = Option<(usize, usize)>;

/// Python's str.isspace: Unicode White_Space plus U+001C..U+001F.
fn space(c: char) -> bool {
    c.is_whitespace() || ('\x1c'..='\x1f').contains(&c)
}

// ponytail: Rust's Alphabetic vs Python's isalnum; they part on some combining marks.
fn word(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

fn key_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || "_.-".contains(c)
}

fn quote(c: Option<&char>) -> bool {
    matches!(c, Some('"' | '\''))
}

fn hspaces(t: &[char], mut i: usize) -> usize {
    while i < t.len() && space(t[i]) && t[i] != '\r' && t[i] != '\n' {
        i += 1;
    }
    i
}

/// ASCII `w` (lower case) at `i`, ASCII case-insensitive.
fn lit(t: &[char], i: usize, w: &str) -> bool {
    t.len() >= i + w.len() && w.chars().zip(&t[i..]).all(|(k, c)| c.is_ascii() && c.to_ascii_lowercase() == k)
}

fn segments(key: &[char]) -> Vec<String> {
    let (mut segs, mut cur) = (Vec::new(), String::new());
    for &c in key {
        if "_.-".contains(c) {
            segs.push(std::mem::take(&mut cur));
            continue;
        }
        if let Some(l) = cur.chars().last() {
            if (l.is_ascii_lowercase() && c.is_ascii_uppercase()) || l.is_ascii_digit() != c.is_ascii_digit() {
                segs.push(std::mem::take(&mut cur));
            }
        }
        cur.push(c);
    }
    segs.push(cur);
    segs.into_iter().filter(|s| !s.is_empty()).map(|s| s.to_ascii_uppercase()).collect()
}

fn secret_key(key: &[char]) -> bool {
    let segs = segments(key);
    let tail = |n: usize| &segs[segs.len().saturating_sub(n)..];
    if segs.is_empty() || BENIGN_KEYS.contains(&segs.join("_").as_str()) || BENIGN_TAILS.contains(&segs[segs.len() - 1].as_str()) || tail(2) == ["KEY", "ID"] {
        return false;
    }
    let has = |kws: &[&str]| segs.iter().any(|s| kws.contains(&s.as_str()));
    has(STRONG) || (segs.len() > 1 && has(WEAK))
}

/// (start, end) of the value at `i`: inside its quotes, to the matching one on the line; else a run to whitespace.
fn value(t: &[char], i: usize) -> Hit {
    if i >= t.len() || space(t[i]) {
        return None;
    }
    if quote(t.get(i)) {
        let mut j = i + 1;
        while j < t.len() && t[j] != t[i] && t[j] != '\n' {
            j += if t[j] == '\\' { 2 } else { 1 };
        }
        if j < t.len() && t[j] == t[i] {
            return (j > i + 1).then_some((i + 1, j));
        }
    }
    Some((i, i + t[i..].iter().take_while(|c| !space(**c)).count()))
}

fn token(t: &[char], i: usize) -> usize {
    i + t[i.min(t.len())..].iter().take_while(|c| !space(**c) && !"\"',;".contains(**c)).count()
}

fn line_end(t: &[char], i: usize) -> usize {
    i + t[i.min(t.len())..].iter().take_while(|c| **c != '\r' && **c != '\n').count()
}

const VENDOR: &[&str] = &["sk-ant-", "github_pat_", "glpat-", "ghp_", "gho_", "ghu_", "ghs_", "ghr_", "xoxa-", "xoxb-", "xoxp-"];
const VENDOR_MIN: usize = 8;

fn b64url(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '_' || c == '-'
}

fn ident(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '_'
}

fn run(t: &[char], i: usize, ok: fn(char) -> bool) -> usize {
    i + t[i.min(t.len())..].iter().take_while(|c| ok(**c)).count()
}

/// `s` at `i`, case-sensitive (Python str.startswith).
fn starts(t: &[char], i: usize, s: &str) -> bool {
    t.len() >= i + s.chars().count() && s.chars().zip(&t[i..]).all(|(a, b)| a == *b)
}

/// Python str.find(pat, from, to): the first `pat` wholly inside [from, to).
fn find(t: &[char], from: usize, to: usize, pat: &str) -> Option<usize> {
    let n = pat.chars().count();
    (from..to.min(t.len()).saturating_sub(n - 1).max(from)).find(|&i| starts(t, i, pat))
}

fn pem(t: &[char], p: usize) -> Hit {
    if !starts(t, p, "-----BEGIN ") {
        return None;
    }
    let h = find(t, p + 11, t.len(), "PRIVATE KEY-----")?;
    if find(t, p + 11, h, "\n").is_some() {
        return None;
    }
    let k = find(t, h, t.len(), "-----END ").and_then(|e| find(t, e, t.len(), "PRIVATE KEY-----"));
    Some((p, k.map_or(t.len(), |k| k + 16)))
}

fn jwt(t: &[char], p: usize) -> Hit {
    let mut j = p;
    for part in 0..3 {
        if part < 2 && !starts(t, j, "eyJ") {
            return None;
        }
        let e = run(t, j, b64url);
        if part < 2 && (e - j < 4 || t.get(e) != Some(&'.')) {
            return None;
        }
        j = if part < 2 { e + 1 } else { e };
    }
    Some((p, j))
}

fn vendor(t: &[char], p: usize) -> Hit {
    if let Some(pre) = VENDOR.iter().find(|pre| starts(t, p, pre)) {
        let v = p + pre.len();
        let e = run(t, v, b64url);
        return (e - v >= VENDOR_MIN).then_some((v, e));
    }
    let upper = |c: char| c.is_ascii_uppercase() || c.is_ascii_digit();
    (starts(t, p, "AKIA") && run(t, p + 4, upper) == p + 20 && !t.get(p + 20).is_some_and(|c| c.is_ascii_alphanumeric())).then_some((p + 4, p + 20))
}

/// `<prefix>_pw_<name>`: the prefix is the secret; the name says which credential.
fn legacy_pw(t: &[char], p: usize) -> Hit {
    if p > 0 && ident(t[p - 1]) {
        return None;
    }
    let e = run(t, p, ident);
    let k = find(t, p, e, "_pw_")?;
    (k > p && k + 4 < e).then_some((p, k))
}

/// `scheme://user:pw@host`: the pw, up to the authority's last @.
fn userinfo(t: &[char], p: usize) -> Hit {
    if !starts(t, p, "://") || p == 0 || !t[p - 1].is_ascii_alphabetic() {
        return None;
    }
    let a = p + 3 + t[p + 3..].iter().take_while(|c| !space(**c) && !"/?#\"'".contains(**c)).count();
    let at = (p + 3..a).rev().find(|&i| t[i] == '@')?;
    let colon = (p + 3..a).find(|&i| t[i] == ':')?;
    (colon + 1 < at).then_some((colon + 1, at))
}

fn shape(t: &[char], p: usize) -> Hit {
    if p > 0 && b64url(t[p - 1]) && t[p] != ':' {
        return None;
    }
    [pem, jwt, vendor, legacy_pw, userinfo].into_iter().find_map(|m| m(t, p))
}

/// After a header name: optional quote, gap, `:`, gap, optional quote.
fn header_colon(t: &[char], j: usize) -> Option<usize> {
    let j = hspaces(t, j + quote(t.get(j)) as usize);
    if t.get(j) != Some(&':') {
        return None;
    }
    let j = hspaces(t, j + 1);
    Some(j + quote(t.get(j)) as usize)
}

fn header(t: &[char], p: usize) -> Hit {
    if p > 0 && t[p - 1].is_ascii_alphabetic() {
        return None;
    }
    if lit(t, p, "authorization") {
        let j = header_colon(t, p + 13)?;
        let scheme = SCHEMES.iter().find(|s| lit(t, j, s))?;
        let v = hspaces(t, j + scheme.len());
        if v == j + scheme.len() {
            return None;
        }
        let end = if *scheme == "digest" { line_end(t, v) } else { token(t, v) };
        return (end > v).then_some((v, end));
    }
    if lit(t, p, "cookie") {
        let v = header_colon(t, p + 6)?;
        let end = line_end(t, v);
        return (end > v).then_some((v, end));
    }
    None
}

fn bearer(t: &[char], p: usize) -> Hit {
    if (p > 0 && word(t[p - 1])) || !lit(t, p, "bearer") {
        return None;
    }
    let v = p + 6 + t[p + 6..].iter().take_while(|c| space(**c)).count();
    let end = token(t, v);
    (v > p + 6 && end - v >= BEARER_MIN).then_some((v, end))
}

fn cli(t: &[char], p: usize) -> Hit {
    if t[p] != '-' || (p > 0 && key_char(t[p - 1])) {
        return None;
    }
    let k = p + 1 + (t.get(p + 1) == Some(&'-')) as usize;
    for flag in FLAGS {
        let s = k + flag.len();
        if !lit(t, k, flag) || s >= t.len() || !(t[s] == '=' || hspaces(t, s) > s) {
            continue;
        }
        let v = if t[s] == '=' { s + 1 } else { hspaces(t, s) };
        if t[s] != '=' && t.get(v) == Some(&'-') {
            return None;
        }
        return value(t, v);
    }
    None
}

fn kv(t: &[char], p: usize) -> Hit {
    if !key_char(t[p]) || (p > 0 && key_char(t[p - 1])) {
        return None;
    }
    let r = p + t[p..].iter().take_while(|c| key_char(**c)).count();
    let j = hspaces(t, r + quote(t.get(r)) as usize);
    if !matches!(t.get(j), Some('=' | ':')) || t.get(j + 1) == t.get(j) {
        return None;
    }
    let v = hspaces(t, j + 1);
    if secret_key(&t[p..r]) { value(t, v) } else { None }
}

fn sub(t: Vec<char>, m: fn(&[char], usize) -> Hit) -> Vec<char> {
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

/// Every exact occurrence of a value the runner handed the job, longest first, then every layer.
pub fn redact(text: &str, known: &[&str]) -> String {
    let mut vals: Vec<&str> = known.iter().copied().filter(|v| v.chars().count() >= KNOWN_MIN && !R.contains(v)).collect();
    vals.sort_by(|a, b| b.chars().count().cmp(&a.chars().count()).then(a.cmp(b)));
    vals.dedup();
    let text = vals.into_iter().fold(text.to_string(), |t, v| t.replace(v, R));
    [shape, header, bearer, cli, kv].into_iter().fold(text.chars().collect(), sub).into_iter().collect()
}

#[cfg(test)]
mod tests {
    /// Every section of the contract fixture test_pulse_redact runs through scrub_text.
    #[test]
    fn the_contract_fixture() {
        let v: serde_json::Value = serde_json::from_str(include_str!("../../../../contracts/redact.fixture.json")).unwrap();
        let (mut bad, mut n) = (Vec::new(), 0);
        for (sec, cases) in v.as_object().unwrap().iter().filter(|(k, _)| !["contract_version", "why"].contains(&k.as_str())) {
            for c in cases.as_array().unwrap() {
                let (input, want, known) = match c {
                    serde_json::Value::String(s) => (s.as_str(), s.as_str(), vec![]),
                    serde_json::Value::Object(o) => (o["in"].as_str().unwrap(), o["out"].as_str().unwrap(),
                                                     o["known"].as_array().unwrap().iter().map(|k| k.as_str().unwrap()).collect()),
                    p => (p[0].as_str().unwrap(), p[1].as_str().unwrap(), vec![]),
                };
                n += 1;
                let got = super::redact(input, &known);
                if got != want || super::redact(&got, &known) != got {
                    bad.push(format!("[{sec}] {input:?}\n   want {want:?}\n    got {got:?}"));
                }
            }
        }
        assert!(n > 100 && bad.is_empty(), "{} of {n} cases differ:\n{}", bad.len(), bad.join("\n"));
    }
}
