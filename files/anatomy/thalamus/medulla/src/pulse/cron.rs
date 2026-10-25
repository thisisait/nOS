//! Five-field cron in UTC, the subset the Pulse catalog writes: `*`, `n`, `a-b`, lists, `*/s`, `a-b/s`.
//! Parity with Wing's dragonmantank/cron-expression 3.6 is pinned by test_medulla_pulse_cron_parity.py;
//! anything outside the subset (names, `L`, `W`, `#`, `?`, macros) is refused, never guessed.
use time::OffsetDateTime;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Cron {
    minute: u64,
    hour: u64,
    dom: u64,
    month: u64,
    dow: u64,
    /// Both day fields restricted: a day matches either (POSIX cron, and PHP's library).
    either_day: bool,
}

fn field(text: &str, lo: u32, hi: u32) -> Result<u64, String> {
    let num = |s: &str| s.parse::<u32>().ok().filter(|n| (lo..=hi).contains(n)).ok_or_else(|| format!("'{s}' outside {lo}-{hi}"));
    let mut bits = 0u64;
    for part in text.split(',') {
        let (range, step) = match part.split_once('/') {
            Some((r, s)) => (r, s.parse::<u32>().ok().filter(|s| *s > 0).ok_or_else(|| format!("bad step in '{part}'"))?),
            None => (part, 1),
        };
        let (a, b) = match range.split_once('-') {
            _ if range == "*" => (lo, hi),
            Some((a, b)) => (num(a)?, num(b)?),
            None if step == 1 => (num(range)?, num(range)?),
            None => return Err(format!("'{part}': a step needs * or a range")),
        };
        if a > b {
            return Err(format!("'{range}' runs backwards"));
        }
        for n in (a..=b).step_by(step as usize) {
            bits |= 1 << n;
        }
    }
    Ok(bits)
}

impl Cron {
    pub fn parse(expr: &str) -> Result<Cron, String> {
        let f: Vec<&str> = expr.split_whitespace().collect();
        let [mi, h, dom, mon, dow] = f[..] else { return Err(format!("'{expr}': five fields, got {}", f.len())) };
        let mut dow_bits = field(dow, 0, 7)?;
        if dow_bits & (1 << 7) != 0 {
            dow_bits = (dow_bits | 1) & !(1 << 7); // 7 is Sunday too
        }
        Ok(Cron {
            minute: field(mi, 0, 59)?,
            hour: field(h, 0, 23)?,
            dom: field(dom, 1, 31)?,
            month: field(mon, 1, 12)?,
            dow: dow_bits,
            either_day: dom != "*" && dow != "*",
        })
    }

    fn day_ok(&self, t: &OffsetDateTime) -> bool {
        let d = self.dom & (1 << t.day()) != 0;
        let w = self.dow & (1 << t.weekday().number_days_from_sunday()) != 0;
        if self.either_day { d || w } else { d && w }
    }

    /// The first minute strictly after `now`'s minute that matches, or None within ~5 years.
    pub fn next_after(&self, now: i64) -> Option<i64> {
        let mut t = now.div_euclid(60) * 60 + 60;
        for _ in 0..200_000 {
            let at = OffsetDateTime::from_unix_timestamp(t).ok()?;
            if self.month & (1 << u8::from(at.month())) == 0 || !self.day_ok(&at) {
                t = (t.div_euclid(86_400) + 1) * 86_400; // UTC: a day is 86 400 s
            } else if self.hour & (1 << at.hour()) == 0 {
                t = (t.div_euclid(3_600) + 1) * 3_600;
            } else if self.minute & (1 << at.minute()) == 0 {
                t += 60;
            } else {
                return Some(t);
            }
        }
        None
    }
}

#[cfg(test)]
mod tests {
    use super::Cron;

    /// The vectors PHP produced (tests/anatomy/test_medulla_pulse_cron_parity.py keeps them true).
    #[test]
    fn every_vector_matches_php() {
        let vs: Vec<serde_json::Value> = serde_json::from_str(include_str!("../../../../../../tests/fixtures/pulse_cron.json")).unwrap();
        assert!(vs.len() > 200, "the vector file shrank");
        let wrong: Vec<String> = vs
            .iter()
            .filter_map(|v| {
                let (e, now, php) = (v["expr"].as_str()?, v["now"].as_i64()?, v["next"].as_str()?);
                let got = Cron::parse(e).ok().and_then(|c| c.next_after(now)).map(super::super::iso);
                (got.as_deref() != Some(php)).then(|| format!("{e} @{now}: php {php}, medulla {got:?}"))
            })
            .collect();
        assert!(wrong.is_empty(), "{}", wrong.join("\n"));
    }

    #[test]
    fn outside_the_subset_is_refused() {
        for e in ["", "* * * *", "@daily", "0 0 L * *", "0 0 * * MON", "0 0 * JAN *", "60 * * * *", "5/10 * * * *", "0 0 ? * 1", "5-1 * * * *"] {
            assert!(Cron::parse(e).is_err(), "{e} parsed");
        }
        assert_eq!(Cron::parse("0 0 30 2 *").unwrap().next_after(0), None, "Feb 30 never comes");
    }

    /// Where PHP's library is wrong, the medulla is not bug-compatible: it says 11:05, PHP 11:10.
    #[test]
    fn a_list_holding_a_range_keeps_its_first_value() {
        let t = Cron::parse("5,10-12 * * * *").unwrap().next_after(1_792_060_397); // 2026-10-15 10:33:17
        assert_eq!(t.map(super::super::iso).as_deref(), Some("2026-10-15T11:05:00+00:00"));
    }
}
