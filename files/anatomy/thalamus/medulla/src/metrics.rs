//! Wing's /api/v1/metrics, served by the medulla behind the Caddy seam (ssot/doctrine/medulla.md §5).
//! The same four families, SQL and label escaping as Api\MetricsPresenter; anonymous read, loopback
//! only, as PHP enforces today. wing.db is opened read-only: PHP stays its one writer (§4).
use rusqlite::types::ValueRef;
use rusqlite::{Connection, OpenFlags};
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::time::Duration;

const MAX_HEAD: usize = 8 * 1024;
const CONTENT_TYPE: &str = "text/plain; version=0.0.4; charset=utf-8";

/// Bind 127.0.0.1:<port> and answer until the process ends; one thread per connection.
pub fn serve(db: PathBuf, port: u16) -> std::io::Result<()> {
    let listener = TcpListener::bind(("127.0.0.1", port))?;
    println!("medulla wing: listening on {}", listener.local_addr()?);
    for stream in listener.incoming().flatten() {
        let db = db.clone();
        std::thread::spawn(move || {
            let _ = handle(stream, &db);
        });
    }
    Ok(())
}

fn handle(mut s: TcpStream, db: &Path) -> std::io::Result<()> {
    s.set_read_timeout(Some(Duration::from_secs(5)))?;
    let mut head = Vec::new();
    let mut buf = [0u8; 1024];
    while !head.windows(4).any(|w| w == b"\r\n\r\n") {
        if head.len() > MAX_HEAD {
            return respond(&mut s, "413 Payload Too Large", "text/plain", b"request too large\n", false);
        }
        let n = s.read(&mut buf)?;
        if n == 0 {
            return Ok(());
        }
        head.extend_from_slice(&buf[..n]);
    }
    let head = String::from_utf8_lossy(&head);
    let mut lines = head.split("\r\n");
    let mut req = lines.next().unwrap_or_default().split(' ');
    let (method, target) = (req.next().unwrap_or_default(), req.next().unwrap_or_default());
    let headers: Vec<(String, String)> = lines.filter_map(|l| l.split_once(':')).map(|(k, v)| (k.trim().to_ascii_lowercase(), v.trim().to_owned())).collect();
    let header = |name: &str| headers.iter().find(|(k, _)| k == name).map(|(_, v)| v.clone());
    if headers.iter().any(|(k, v)| k == "content-length" && v.parse::<usize>().map_or(true, |n| n > MAX_HEAD)) {
        return respond(&mut s, "413 Payload Too Large", "text/plain", b"request too large\n", false);
    }
    let (path, query) = target.split_once('?').unwrap_or((target, ""));
    let head_only = method == "HEAD";
    if method == "GET" {
        if let Some((code, body)) = crate::pulse_reads::answer(db, path, query, &header) {
            let status = match code { 200 => "200 OK", 401 => "401 Unauthorized", 403 => "403 Forbidden", 404 => "404 Not Found", _ => "500 Internal Server Error" };
            return respond(&mut s, status, "application/json; charset=utf-8", body.to_string().as_bytes(), false);
        }
    }
    if !(method == "GET" || head_only) || path != "/api/v1/metrics" {
        return respond(&mut s, "404 Not Found", "text/plain", b"not found\n", head_only);
    }
    match render(db) {
        Ok(body) => respond(&mut s, "200 OK", CONTENT_TYPE, body.as_bytes(), head_only),
        Err(e) => respond(&mut s, "500 Internal Server Error", "text/plain", format!("{e}\n").as_bytes(), head_only),
    }
}

fn respond(s: &mut TcpStream, status: &str, ctype: &str, body: &[u8], head_only: bool) -> std::io::Result<()> {
    let hdr = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n",
        body.len()
    );
    s.write_all(hdr.as_bytes())?;
    if !head_only {
        s.write_all(body)?;
    }
    s.flush()
}

/// PHP's `(string) ($v ?? 'unknown')`.
fn text(v: ValueRef) -> String {
    match v {
        ValueRef::Null => "unknown".into(),
        ValueRef::Integer(i) => i.to_string(),
        ValueRef::Real(f) => f.to_string(),
        ValueRef::Text(t) | ValueRef::Blob(t) => String::from_utf8_lossy(t).into_owned(),
    }
}

/// PHP's `(int) ($v ?? 0)`.
fn int(v: ValueRef) -> i64 {
    match v {
        ValueRef::Integer(i) => i,
        ValueRef::Real(f) => f as i64,
        ValueRef::Text(t) => std::str::from_utf8(t).ok().and_then(|t| t.trim().parse().ok()).unwrap_or(0),
        _ => 0,
    }
}

fn g<'a>(r: &'a rusqlite::Row, i: usize) -> ValueRef<'a> {
    r.get_ref(i).unwrap_or(ValueRef::Null)
}

fn esc(v: &str) -> String {
    v.replace('\\', "\\\\").replace('"', "\\\"").replace('\n', "\\n")
}

fn rows(db: &Connection, sql: &str, mut each: impl FnMut(&rusqlite::Row) -> String) -> rusqlite::Result<Vec<String>> {
    let mut st = db.prepare(sql)?;
    let mut rs = st.query([])?;
    let mut out = Vec::new();
    while let Some(r) = rs.next()? {
        out.push(each(r));
    }
    Ok(out)
}

pub fn render(db: &Path) -> rusqlite::Result<String> {
    let db = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
    db.busy_timeout(Duration::from_secs(5))?;
    let mut l: Vec<String> = vec![
        "# HELP nos_e2e_journey_runs_total Total e2e journey runs by name and final status.".into(),
        "# TYPE nos_e2e_journey_runs_total counter".into(),
    ];
    l.extend(rows(&db,
        "SELECT json_extract(result_json, '$.journey') AS journey, json_extract(result_json, '$.status') AS status, COUNT(*) AS n
         FROM events WHERE type = 'e2e_journey_end' GROUP BY journey, status",
        |r| format!("nos_e2e_journey_runs_total{{journey=\"{}\",status=\"{}\"}} {}", esc(&text(g(r, 0))), esc(&text(g(r, 1))), int(g(r, 2))),
    )?);
    l.extend([
        String::new(),
        "# HELP nos_e2e_journey_step_duration_ms_sum Sum of step durations (ms) by journey + step.".into(),
        "# HELP nos_e2e_journey_step_duration_ms_count Count of step samples by journey + step.".into(),
        "# TYPE nos_e2e_journey_step_duration_ms_sum counter".into(),
        "# TYPE nos_e2e_journey_step_duration_ms_count counter".into(),
    ]);
    for pair in rows(&db,
        "SELECT json_extract(result_json, '$.journey') AS journey, json_extract(result_json, '$.step') AS step,
                json_extract(result_json, '$.status') AS status,
                SUM(CAST(json_extract(result_json, '$.duration_ms') AS INTEGER)) AS sum_ms, COUNT(*) AS n
         FROM events WHERE type = 'e2e_journey_step' GROUP BY journey, step, status",
        |r| {
            let lbl = format!("{{journey=\"{}\",step=\"{}\",status=\"{}\"}}", esc(&text(g(r, 0))), esc(&text(g(r, 1))), esc(&text(g(r, 2))));
            format!("nos_e2e_journey_step_duration_ms_sum{lbl} {}\nnos_e2e_journey_step_duration_ms_count{lbl} {}", int(g(r, 3)), int(g(r, 4)))
        },
    )? {
        l.push(pair);
    }
    l.extend([
        String::new(),
        "# HELP nos_e2e_journey_last_run_timestamp Unix timestamp of the most recent end event per journey.".into(),
        "# TYPE nos_e2e_journey_last_run_timestamp gauge".into(),
    ]);
    l.extend(rows(&db,
        "SELECT json_extract(result_json, '$.journey') AS journey, json_extract(result_json, '$.status') AS status,
                MAX(strftime('%s', ts)) AS ts
         FROM events WHERE type = 'e2e_journey_end' GROUP BY journey, status",
        |r| format!("nos_e2e_journey_last_run_timestamp{{journey=\"{}\",status=\"{}\"}} {}", esc(&text(g(r, 0))), esc(&text(g(r, 1))), int(g(r, 2))),
    )?);
    l.extend([
        String::new(),
        "# HELP nos_pulse_jobs Pulse job catalog state (1 = matches state, 0 otherwise).".into(),
        "# TYPE nos_pulse_jobs gauge".into(),
    ]);
    // The emergency halt is one file (NOS_HALT_FILE, else ~/.nos/halt; row medulla-admin-halt):
    // while it exists every job not paused by hand is emergency_halted.
    let halted = thalamus::state::halt_file().is_file();
    l.extend(rows(&db,
        "SELECT id, CASE WHEN paused = 1 AND paused_reason LIKE 'emergency-halt:%' THEN 'emergency_halted'
                         WHEN paused = 1 THEN 'manually_paused' ELSE 'unpaused' END AS state
         FROM pulse_jobs WHERE removed_at IS NULL",
        |r| {
            let state = text(g(r, 1));
            let state = if halted && state == "unpaused" { "emergency_halted".to_string() } else { state };
            format!("nos_pulse_jobs{{job_id=\"{}\",state=\"{}\"}} 1", esc(&text(g(r, 0))), esc(&state))
        },
    )?);
    Ok(l.join("\n") + "\n")
}
