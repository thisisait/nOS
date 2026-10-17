//! Iris plans in cortex-lang (seed row iris-speaks-cortex-lang): the model emits ONE pipeline, the
//! cortex organ validates it (POST /agent/v1/validate, never a copy of its registry here), and this
//! maps it to the thalamus's own tool calls. What the table below does not carry is refused, and
//! serve falls back to plain tool calling. ?commit and dry_run are ignored: the card is the gate.

use serde_json::{json, Map, Value};

/// The opcode registry this mapper was written against (contract v3); any other is refused.
pub const REGISTRY_HASH: &str = "cx1:8250d05e5e32afb7";
/// query_rows' where ops, plus the two words matched() reads as lt and gt.
const OPS: [&str; 9] = ["eq", "neq", "in", "contains", "lt", "gt", "between", "before", "after"];
/// The opcodes the mapper carries: the JSON-schema engine's enum.
const MAPPED: [&str; 8] = ["get", "filter", "rank", "aggregate", "show", "insert", "update", "delete"];
/// The params plan() reads, per opcode; the organ leaves a db: stage's params open, so any other is refused here.
/// dry_run, commit and idempotency_key are read as nothing on purpose: the card is the gate.
const READS: [(&str, &[&str]); 8] = [("get", &["limit", "fields"]), ("filter", &["where", "q"]), ("rank", &["by", "dir", "limit"]),
    ("aggregate", &["op", "by", "y"]), ("show", &["kind", "chart", "x", "y", "title", "unit"]),
    ("insert", &["set", "dry_run", "commit", "idempotency_key"]), ("update", &["set", "dry_run", "commit", "idempotency_key"]),
    ("delete", &["dry_run", "commit", "idempotency_key"])];
/// The v3 params the mapper reads (registry v3), each with its JSON type.
const PARAMS: [(&str, &str); 14] = [("limit", "integer"), ("fields", "string"), ("where", "string"), ("q", "string"),
    ("by", "string"), ("dir", "string"), ("op", "string"), ("y", "string"), ("kind", "string"), ("chart", "string"),
    ("x", "string"), ("title", "string"), ("unit", "string"), ("set", "string")];

/// The organ on loopback and its read-only token (CORTEX_TOKEN_RO).
#[derive(Debug, Clone)]
pub struct Cortex {
    pub url: String,
    pub token: String,
}

/// One stage of the flat AST: what the JSON-schema engine emits and the organ's AST is read into.
#[derive(Debug, Clone, PartialEq)]
pub struct Stage {
    pub op: String,
    pub operand: Option<String>,
    pub params: Map<String, Value>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Engine {
    /// llama.cpp's llama-server: state/cortex-lang.gbnf sent with the request.
    Gbnf,
    /// Ollama GGUF: `response_format` json_schema of the flat AST.
    JsonSchema,
    /// Everything else (Ollama MLX 501s on any format): free text and one repair round.
    Free,
}

impl Engine {
    pub fn of(backend: &str) -> Engine {
        match backend {
            // ponytail: no llamacpp register row (ruling B(c) 2026-10-17), so Gbnf is unreachable;
            // a llamacpp row/role comes only after the Ollama GGUF and MLX measurements.
            "llamacpp" => Engine::Gbnf,
            "ollama" => Engine::JsonSchema,
            _ => Engine::Free,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Engine::Gbnf => "llamacpp-gbnf",
            Engine::JsonSchema => "ollama-json-schema",
            Engine::Free => "unconstrained",
        }
    }
}

/// {stages: [{op, operand?, params}]} as Stages.
pub fn stages_of(v: &Value) -> Result<Vec<Stage>, String> {
    let st = v.get("stages").and_then(Value::as_array).filter(|s| !s.is_empty()).ok_or("no `stages` list")?;
    st.iter().map(|s| Ok(Stage {
        op: s.get("op").and_then(Value::as_str).ok_or("a stage has no `op`")?.to_string(),
        operand: s.get("operand").and_then(Value::as_str).filter(|o| !o.is_empty()).map(str::to_string),
        // the closed schema makes a small model fill every param it may: "" means unset (live 2026-10-17)
        params: s.get("params").and_then(Value::as_object).into_iter().flatten()
            .filter(|(_, v)| v.as_str() != Some("")).map(|(k, v)| (k.clone(), v.clone())).collect(),
    })).collect()
}

/// The source the organ validates: `op(operand, key=value, ...)` joined by ` | `, params in key order.
pub fn render(stages: &[Stage]) -> String {
    stages.iter().map(|s| {
        let args: Vec<String> = s.operand.iter().cloned().chain(s.params.iter().map(|(k, v)| match v {
            Value::String(t) => format!("{k}={}", Value::String(t.clone())),
            v => format!("{k}={v}"),
        })).collect();
        format!("{}({})", s.op, args.join(", "))
    }).collect::<Vec<_>>().join(" | ")
}

/// A free-text answer's pipeline: from the first line that opens with an opcode call (or a source),
/// joined with each following line that continues it (`| ...`, or after a trailing `|`); fences and
/// prose around it are not the plan. No such line: the first non-empty one, for the organ to refuse.
pub fn extract(text: &str) -> String {
    let lines: Vec<&str> = text.lines().map(str::trim).filter(|l| !l.starts_with("```")).collect();
    let opens = |l: &str| l.starts_with('@') || l.split_once('(').is_some_and(|(h, _)| !h.is_empty()
        && h.starts_with(|c: char| c.is_ascii_lowercase()) && h.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-'));
    let Some(at) = lines.iter().position(|l| opens(l)) else {
        return lines.iter().find(|l| !l.is_empty()).unwrap_or(&"").to_string();
    };
    let mut out = lines[at].to_string();
    for l in lines[at + 1..].iter().filter(|l| !l.is_empty()) {
        if !(l.starts_with('|') || out.ends_with('|')) {
            break;
        }
        out = format!("{out} {l}");
    }
    out
}

/// A db: operand as the organ's lexer reads it: a dot only between two segments.
pub const DB_OPERAND: &str = "^db:[A-Za-z0-9_-]+(\\.[A-Za-z0-9_-]+)*$";

/// One opcode's branch: (op, operand: none | db | db or none, params, required params).
/// Per cortex-opcodes.ts v3; tests/cortex_plan.rs reads the registry and holds each branch to it.
fn branch(op: &str, operand: Option<bool>, params: Value, required: &[&str]) -> Value {
    let operand = match operand {
        None => json!({"const": ""}),
        Some(true) => json!({"type": "string", "pattern": DB_OPERAND}),
        Some(false) => json!({"type": "string", "pattern": format!("^({})?$", &DB_OPERAND[1..DB_OPERAND.len() - 1])}),
    };
    json!({"type": "object", "additionalProperties": false, "required": ["op", "operand", "params"], "properties": {
        "op": {"const": op}, "operand": operand,
        "params": {"type": "object", "additionalProperties": false, "required": required, "properties": params}}})
}

/// The JSON schema the Ollama engine constrains the plan call to. `properties` is the union every
/// stage may hold; `anyOf` is what each opcode takes, which is what a constrained decoder follows.
pub fn ast_schema() -> Value {
    let s = |d: &str| json!({"type": "string", "description": d});
    let limit = json!({"type": "integer", "minimum": 1, "maximum": 50});
    // an open union let the organ refuse filter(db:t), filter(limit=0) and aggregate(by=x) (probe 2026-10-17)
    let per_op = json!([
        branch("get", Some(true), json!({"limit": limit, "fields": s("comma-separated column keys")}), &[]),
        branch("filter", None, json!({"where": s("<column> <op> <value>"), "q": s("text anywhere in the row")}), &[]),
        branch("rank", None, json!({"by": s("a column key"), "dir": {"enum": ["asc", "desc"]}, "limit": limit}), &["by"]),
        branch("aggregate", Some(false), json!({"op": {"enum": ["count", "sum", "avg"]}, "by": s("a column key to group by"),
            "y": s("a number column key, for sum and avg")}), &["op"]),
        branch("show", Some(false), json!({"kind": {"enum": ["chart", "kpi", "table"]}, "chart": {"enum": ["bar", "line", "pie"]},
            "x": s("a column key"), "y": s("a number column key"), "title": s("the heading"), "unit": s("a kpi's unit")}), &["kind"]),
        branch("insert", Some(true), json!({"set": {"type": "string", "minLength": 3, "description": "col=value;col=value"}}), &["set"]),
        branch("update", Some(true), json!({"set": {"type": "string", "minLength": 3, "description": "col=value;col=value"}}), &["set"]),
        branch("delete", Some(true), json!({}), &[]),
    ]);
    json!({"type": "object", "additionalProperties": false, "required": ["stages"], "properties": {
        "stages": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "object", "additionalProperties": false,
            // a closed param set and a shaped operand: an open one let an 8B model write get(db="t")
            "required": ["op", "operand", "params"], "anyOf": per_op, "properties": {
                "op": {"enum": MAPPED},
                "operand": {"type": "string", "pattern": "^(db:[A-Za-z0-9_.-]+)?$", "description": "db:<table id>, or empty"},
                "params": {"type": "object", "additionalProperties": false,
                           "properties": PARAMS.iter().map(|(k, t)| (k.to_string(), json!({"type": t}))).collect::<Map<String, Value>>()}}}}}})
}

/// The plan call's system prompt: the v3 lines the mapper carries, the mini-syntaxes, the tables.
pub fn primer(engine: Engine, catalogue: &str) -> String {
    let answer = match engine {
        Engine::JsonSchema => "Answer as JSON {\"stages\": [{\"op\", \"operand\", \"params\"}]}: one stage per opcode; operand is \"db:<table id>\" (never a param) or \"\" when the stage takes none.",
        _ => "Answer with the pipeline only: one line, no prose, no code fence.",
    };
    format!("You plan the person's request as ONE cortex-lang pipeline. {answer}
Pipeline: opcode(db:<table id>, key=\"value\", ...) | opcode(...); every string value in double quotes, a number bare.
get(db:T, limit=N, fields=\"col,col\")  rows of table T
filter(where=\"<column> <op> <value>\", q=\"text\")  one condition per filter, chain filters for AND; op is eq neq in contains lt gt between; in and between take comma-separated values
rank(by=\"col\", dir=\"desc\", limit=N)  order and cut
aggregate(op=\"count\"|\"sum\"|\"avg\", by=\"col\", y=\"col\")  count rows, or sum or avg the number column y; by groups
show(kind=\"chart\"|\"kpi\"|\"table\", chart=\"bar\"|\"line\"|\"pie\", x=\"col\", title=\"...\", unit=\"...\")  a chart needs aggregate by, x is that column; a kpi is one total
insert(db:T, set=\"col=value;col=value\")  update(db:T, set=\"col=value\")  delete(db:T)  a write acts on exactly one row the filters find; the person approves it
Example: open todos per status as a bar chart -> get(db:todos) | filter(where=\"status eq open\") | aggregate(op=\"count\", by=\"status\") | show(kind=\"chart\", chart=\"bar\", x=\"status\")
Tables:
{catalogue}")
}

/// `"<column> <op> <value>"`: (column, op, value); in and between give a list.
/// The symbols a model writes for an op, as SQL does (probe 2026-10-17); no inclusive >= or <=.
const SYMBOLS: [(&str, &str); 5] = [("!=", "neq"), ("<>", "neq"), ("=", "eq"), (">", "gt"), ("<", "lt")];

pub fn parse_where(s: &str) -> Result<(String, String, Value), String> {
    let bad = || format!("where {s:?} is not \"<column> <op> <value>\" (op: eq, neq, in, contains, lt, gt, between)");
    // ASCII lowercase keeps byte offsets: EQ is eq
    let low = s.to_ascii_lowercase();
    let words = OPS.iter().map(|op| (*op, *op));
    let (at, said, op) = words.chain(SYMBOLS).filter_map(|(w, op)| low.find(&format!(" {w} ")).map(|i| (i, w, op))).min().ok_or_else(bad)?;
    let (col, val) = (s[..at].trim(), s[at + said.len() + 2..].trim().trim_matches(|c| c == '"' || c == '\''));
    if col.is_empty() || val.is_empty() {
        return Err(bad());
    }
    let list = || json!(val.split(',').map(str::trim).collect::<Vec<_>>());
    Ok((col.to_string(), op.to_string(), if matches!(op, "in" | "between") { list() } else { json!(val) }))
}

/// `"key=value;key=value"` in order; a value may hold `=`, an empty one clears the cell.
pub fn parse_set(s: &str) -> Result<Vec<(String, String)>, String> {
    let mut out: Vec<(String, String)> = vec![];
    for part in s.split(';').map(str::trim).filter(|p| !p.is_empty()) {
        let (k, v) = part.split_once('=').ok_or(format!("set {s:?} is not \"key=value;key=value\""))?;
        let k = k.trim().to_string();
        if k.is_empty() || out.iter().any(|(o, _)| *o == k) {
            return Err(format!("set {s:?} names a column twice or none"));
        }
        out.push((k, v.trim().to_string()));
    }
    if out.is_empty() {
        return Err("a write needs set=\"key=value;...\"".into());
    }
    Ok(out)
}

/// What a pipeline asks, before its table and columns are resolved.
#[derive(Debug, Default)]
pub struct Plan {
    pub table: String,
    pub wheres: Vec<(String, String, Value)>,
    pub q: Option<String>,
    pub fields: Vec<String>,
    pub limit: Option<i64>,
    pub order: Option<(String, String)>,
    /// (op, by, y)
    pub agg: Option<(String, Option<String>, Option<String>)>,
    pub show: Option<Map<String, Value>>,
    /// (insert|update|delete, set)
    pub write: Option<(String, Vec<(String, String)>)>,
}

fn str_of(p: &Map<String, Value>, k: &str) -> Option<String> {
    p.get(k).and_then(Value::as_str).filter(|v| !v.is_empty()).map(str::to_string)
}

/// The mapping table, by opcode and namespace; a source other than the person's turn is refused.
pub fn plan(source: Option<&str>, stages: &[Stage]) -> Result<Plan, String> {
    if let Some(s) = source.filter(|s| !matches!(*s, "@input" | "@user")) {
        return Err(format!("source {s} has no thalamus mapping"));
    }
    let mut p = Plan::default();
    for s in stages {
        if let Some(end) = p.show.as_ref().map(|_| "show").or(p.write.as_ref().map(|w| w.0.as_str())) {
            return Err(format!("{}() follows {end}(): a pipeline ends at show or a write", s.op));
        }
        if !MAPPED.contains(&s.op.as_str()) {
            return Err(format!("{}() has no thalamus mapping", s.op));
        }
        let reads = READS.iter().find(|(o, _)| *o == s.op).map_or(&[][..], |r| r.1);
        if let Some(k) = s.params.keys().find(|k| !reads.contains(&k.as_str())) {
            return Err(format!("{}() has no param `{k}` the thalamus reads; it reads {}", s.op,
                               reads.iter().filter(|r| !matches!(**r, "dry_run" | "commit" | "idempotency_key")).copied().collect::<Vec<_>>().join(", ")));
        }
        if let Some(o) = &s.operand {
            match o.split_once(':') {
                Some(("db", t)) if p.table.is_empty() || p.table == t => p.table = t.to_string(),
                Some(("db", _)) => return Err(format!("{}({o}) names a second table after {}; one pipeline reads one table", s.op, p.table)),
                _ => return Err(format!("{}({o}): namespace {} has no thalamus mapping; only db: tables do",
                                        s.op, o.split(':').next().unwrap_or(o))),
            }
        }
        let (prm, int) = (&s.params, |k: &str| s.params.get(k).and_then(Value::as_i64));
        match s.op.as_str() {
            "get" => {
                p.limit = int("limit").or(p.limit);
                p.fields = str_of(prm, "fields").map(|f| f.split(',').map(|c| c.trim().to_string()).filter(|c| !c.is_empty()).collect())
                    .unwrap_or_default();
            }
            "filter" => {
                if let Some(w) = str_of(prm, "where") {
                    p.wheres.push(parse_where(&w)?);
                }
                p.q = str_of(prm, "q").or(p.q.take());
            }
            "rank" => {
                let by = str_of(prm, "by").ok_or("rank() needs by=<column>")?;
                p.order = Some((by, str_of(prm, "dir").unwrap_or_else(|| "desc".into())));
                p.limit = int("limit").or(p.limit);
            }
            "aggregate" => p.agg = Some((str_of(prm, "op").unwrap_or_else(|| "count".into()), str_of(prm, "by"), str_of(prm, "y"))),
            "show" => p.show = Some(prm.clone()),
            w => {
                let set = if w == "delete" { vec![] } else { parse_set(&str_of(prm, "set").unwrap_or_default())? };
                if p.agg.is_some() {
                    return Err(format!("{w}() after aggregate(): a write acts on a row, not a total"));
                }
                p.write = Some((w.to_string(), set));
            }
        }
    }
    if p.table.is_empty() {
        return Err("the pipeline names no db: table".into());
    }
    Ok(p)
}

/// The plan as tool calls: `info` is serve's table_info (id, then title; the septum), `check(args,
/// read)` its matched() over query_rows args, giving the matched row ids when `read`.
pub fn calls(p: &Plan, info: impl Fn(&str) -> Result<(String, Value), String>,
             check: impl Fn(&Value, bool) -> Result<Vec<String>, String>) -> Result<Vec<(String, Value)>, String> {
    let (table, info) = info(&p.table)?;
    let title = info.pointer("/data/title").and_then(Value::as_str).unwrap_or(&table).to_string();
    let schema: Vec<&Value> = info.pointer("/data/schema/columns").and_then(Value::as_array).into_iter().flatten()
        .filter(|c| c["key"].is_string()).collect();
    let keys: Vec<&str> = schema.iter().filter_map(|c| c["key"].as_str()).collect();
    // A column by its exact key, else by one key or label in any case.
    let col = |name: &str| -> Result<(String, String), String> {
        let hit: Vec<&&Value> = schema.iter().filter(|c| c["key"] == name).collect();
        let hit = if hit.is_empty() {
            schema.iter().filter(|c| [&c["key"], &c["label"]].iter().any(|v| v.as_str().is_some_and(|v| v.eq_ignore_ascii_case(name)))).collect()
        } else { hit };
        match hit.as_slice() {
            [c] => Ok((c["key"].as_str().unwrap_or_default().into(), c["kind"].as_str().unwrap_or_default().into())),
            _ => Err(format!("no column `{name}` in {title}; columns: {}", keys.join(", "))),
        }
    };
    let mut q = json!({"table": table});
    let wheres = p.wheres.iter().map(|(c, op, v)| Ok(json!({"column": col(c)?.0, "op": op, "value": v}))).collect::<Result<Vec<_>, String>>()?;
    let mut found = json!({"table": table});
    if !wheres.is_empty() {
        found["where"] = json!(wheres);
    }
    if let Some(s) = &p.q {
        found["q"] = json!(s);
    }
    for k in ["where", "q"] {
        if let Some(v) = found.get(k) {
            q[k] = v.clone();
        }
    }
    if !p.fields.is_empty() {
        q["columns"] = json!(p.fields.iter().map(|f| col(f).map(|c| c.0)).collect::<Result<Vec<_>, _>>()?);
    }
    if let Some((by, dir)) = &p.order {
        q["order_by"] = json!({"column": col(by)?.0, "dir": dir});
    }
    if let Some(n) = p.limit {
        q["limit"] = json!(n);
    }
    let (op, by, y) = match &p.agg {
        Some((op, by, y)) => (Some(op.clone()), by.as_deref().map(col).transpose()?.map(|c| c.0), y.as_deref().map(col).transpose()?.map(|c| c.0)),
        None => (None, None, None),
    };
    let kind = p.show.as_ref().and_then(|s| str_of(s, "kind"));
    match kind.as_deref() {
        Some("chart") | Some("kpi") => {
            let s = p.show.as_ref().unwrap_or_else(|| unreachable!());
            let kpi = kind.as_deref() == Some("kpi");
            if let Some(b) = by.as_ref().filter(|_| kpi) {
                return Err(format!("show(kind=kpi) is one total; aggregate(by={b}) groups it"));
            }
            let x = if kpi { None } else {
                Some(str_of(s, "x").map(|x| col(&x).map(|c| c.0)).transpose()?.or(by).ok_or("show(kind=chart) needs aggregate(by=<column>) or x")?)
            };
            let y = str_of(s, "y").map(|y| col(&y).map(|c| c.0)).transpose()?.or(y);
            let op = op.unwrap_or_else(|| "count".into());
            let mut src = json!({"query": found, "op": op});
            let mut probe = found.clone();
            probe["op"] = json!(op);
            if let Some(x) = &x {
                src["x"] = json!(x);
                probe["group_by"] = json!(x);
            }
            if let Some(y) = &y {
                src["y"] = json!(y);
                probe["y"] = json!(y);
            }
            check(&probe, false)?;
            let mut props = Map::new();
            if let Some(t) = str_of(s, "title") {
                props.insert("title".into(), json!(t));
            }
            let component = if kpi {
                props.entry("title").or_insert(json!(format!("{op} of {title}")));
                if let Some(u) = str_of(s, "unit") {
                    props.insert("unit".into(), json!(u));
                }
                json!({"kind": "kpi", "props": props})
            } else {
                // ponytail: show() refuses a chart with no points before its source replaces the series; one placeholder point.
                props.insert("chart".into(), json!(str_of(s, "chart").unwrap_or_else(|| "bar".into())));
                props.insert("x".into(), json!("category"));
                props.insert("series".into(), json!([{"name": op, "points": [["-", 0]]}]));
                json!({"kind": "chart", "props": props})
            };
            return Ok(vec![("show".into(), json!({"component": component, "source": src}))]);
        }
        None | Some("table") | Some("list") | Some("record") => {}
        Some(k) => return Err(format!("show(kind={k}) has no thalamus mapping")),
    }
    if let Some(op) = op {
        q["op"] = json!(op);
        if let Some(by) = by {
            q["group_by"] = json!(by);
        }
        if let Some(y) = y {
            q["y"] = json!(y);
        }
    }
    let Some((w, set)) = &p.write else {
        check(&q, false)?;
        return Ok(vec![("query_rows".into(), q)]);
    };
    let values = set.iter().map(|(k, v)| {
        let (key, kind) = col(k)?;
        let typed = match (kind.as_str(), v.as_str()) {
            (_, "") => Value::Null,
            ("number", n) => n.parse::<i64>().map(Value::from).or_else(|_| n.parse::<f64>().map(Value::from))
                .map_err(|_| format!("{key} is a number, not {n:?}"))?,
            ("bool", b) => json!(b == "true"),
            (_, t) => json!(t),
        };
        Ok((key, typed))
    }).collect::<Result<Map<String, Value>, String>>()?;
    if w == "insert" {
        let look = json!({"table": table, "limit": 0});
        check(&look, false)?;
        return Ok(vec![("query_rows".into(), look), ("propose_row_insert".into(), json!({"table": table, "values": values}))]);
    }
    let hits = check(&q, true)?;
    let [row] = hits.as_slice() else {
        return Err(format!("{w} acts on exactly one row; the pipeline matched {} rows of {title}: filter until one is left", hits.len()));
    };
    let card = if w == "update" {
        ("propose_row_edit".to_string(), json!({"table": table, "row_id": row, "values": values}))
    } else {
        ("propose_row_delete".to_string(), json!({"table": table, "row_id": row}))
    };
    Ok(vec![("query_rows".into(), q), card])
}

/// One organ issue as the repair round says it: where, which opcode and key, and what it takes; the
/// generic `message` alone named none of them (cortex-lang.ts issue()).
fn said_error(e: &Value) -> String {
    let msg = e["message"].as_str().unwrap_or("?");
    let (d, stage) = (&e["detail"], e["stage"].as_u64());
    if !d.is_object() && stage.is_none() {
        return msg.to_string();
    }
    let mut out = stage.map(|s| format!("stage {} ", s + 1)).unwrap_or_default();
    if let Some(op) = d["opcode"].as_str() {
        out.push_str(&format!("{op}(): "));
    }
    out.push_str(e["code"].as_str().unwrap_or("invalid"));
    if let Some(k) = d["key"].as_str() {
        out.push_str(&format!(" `{k}`"));
    }
    out.push_str(&format!(" ({msg})"));
    if let Some(a) = d["allowed"].as_array() {
        out.push_str(&format!("; allowed: {}", a.iter().filter_map(Value::as_str).collect::<Vec<_>>().join(", ")));
    }
    if let Some(t) = d["expectedType"].as_str() {
        out.push_str(&format!("; expected {t}, got {}", d["got"].as_str().unwrap_or("?")));
    }
    out
}

/// What the organ said of `source`: Ok(stages, source) valid, Err(errors) invalid; the outer Err
/// is the organ unreachable or a registry this mapper was not built for.
#[allow(clippy::type_complexity)]
pub fn validate(c: &Cortex, source: &str) -> Result<Result<(Vec<Stage>, Option<String>, String), Vec<String>>, String> {
    let a = crate::serve::agent(10);
    let url = format!("{}/agent/v1/validate", c.url.trim_end_matches('/'));
    let mut r = a.post(&url).header("Authorization", &format!("Bearer {}", c.token)).send_json(json!({"source": source}))
        .map_err(|e| format!("the cortex organ is unreachable ({e})"))?;
    let status = r.status().as_u16();
    let v: Value = r.body_mut().read_json().map_err(|e| format!("the cortex organ answered {status} with no JSON ({e})"))?;
    let d = v.get("data").filter(|_| status == 200).ok_or(format!("the cortex organ answered {status}"))?;
    if d["valid"] != json!(true) {
        let errs = d["errors"].as_array().into_iter().flatten().map(said_error).collect();
        return Ok(Err(errs));
    }
    let hash = d.pointer("/ast/binding/opcodeRegistryHash").and_then(Value::as_str).unwrap_or("").to_string();
    if hash != REGISTRY_HASH {
        return Err(format!("registry {hash} is not the one this mapper was built for ({REGISTRY_HASH})"));
    }
    let src = d.pointer("/ast/pipeline/source").and_then(Value::as_str).map(str::to_string);
    let stages = d.pointer("/ast/pipeline/stages").and_then(Value::as_array).into_iter().flatten().map(|s| {
        let operands = s["operands"].as_array().cloned().unwrap_or_default();
        let operand = match operands.as_slice() {
            [] => None,
            [o] if o["binding"] == "exact" => Some(format!("{}:{}", o["ns"].as_str().unwrap_or(""), o["surface"].as_str().unwrap_or(""))),
            [o] => return Err(format!("a bracket term ({}) has no thalamus mapping; name the table by id", o["surface"])),
            _ => return Err(format!("{}() with {} operands has no thalamus mapping", s["opcode"].as_str().unwrap_or("?"), operands.len())),
        };
        let params = s["params"].as_object().into_iter().flatten().map(|(k, v)| (k.clone(), v["value"].clone())).collect();
        Ok(Stage { op: s["opcode"].as_str().unwrap_or("").to_string(), operand, params })
    }).collect::<Result<Vec<_>, String>>()?;
    Ok(Ok((stages, src, hash)))
}
