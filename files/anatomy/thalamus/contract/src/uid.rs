//! The end user's uid. Spec: files/anatomy/contracts/face-wing.yml §1; the same
//! rule as face `uid.ts` and Wing `CanonicalUid.php`, gated on one fixture by
//! tests/anatomy/test_face_wing_contract.py.

use unicode_normalization::UnicodeNormalization;

fn is_combining_mark(c: char) -> bool {
    ('\u{0300}'..='\u{036F}').contains(&c)
}

/// NFKD, drop combining marks, lowercase, runs outside [a-z0-9] -> "-",
/// trim "-", cap at 64, trim "-" again.
pub fn fold(s: &str) -> String {
    let lowered: String = s.nfkd().filter(|c| !is_combining_mark(*c)).collect::<String>().to_lowercase();
    let mut out = String::with_capacity(lowered.len());
    for c in lowered.chars() {
        if c.is_ascii_lowercase() || c.is_ascii_digit() {
            out.push(c);
        } else if !out.ends_with('-') {
            out.push('-');
        }
    }
    let trimmed = out.trim_matches('-');
    trimmed[..trimmed.len().min(64)].trim_end_matches('-').to_string()
}

/// fold(username), else fold(email local-part), else fold(raw uid); "" is anonymous.
pub fn canonical(username: &str, email: &str, raw_uid: &str) -> String {
    [username, email.split('@').next().unwrap_or(""), raw_uid]
        .iter()
        .map(|s| fold(s))
        .find(|u| !u.is_empty())
        .unwrap_or_default()
}

/// A non-empty fixed point of fold. Anything else is refused.
pub fn is_canonical(uid: &str) -> bool {
    !uid.is_empty() && fold(uid) == uid
}
