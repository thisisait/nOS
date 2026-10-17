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
        params: s.get("params").and_then(Value::as_object).cloned().unwrap_or_default(),
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

/// A free-text answer's pipeline: the first non-empty line outside a code fence.
pub fn extract(text: &str) -> String {
    text.lines().map(str::trim).find(|l| !l.is_empty() && !l.starts_with("```")).unwrap_or("").to_string()
}

/// The JSON schema the Ollama engine constrains the plan call to.
pub fn ast_schema() -> Value {
    json!({"type": "object", "additionalProperties": false, "required": ["stages"], "properties": {
        "stages": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "object", "additionalProperties": false,
            // a closed param set and a shaped operand: an open one let an 8B model write get(db="t")
            "required": ["op", "operand", "params"], "properties": {
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
Pipeline: opcode(db:<table id>, key=value, ...) | opcode(...); a string value in double quotes.
get(db:T, limit=N, fields=\"col,col\")  rows of table T
filter(where=\"<column> <op> <value>\", q=\"text\")  one condition per filter, chain filters for AND; op is eq neq in contains lt gt between; in and between take comma-separated values
rank(by=col, dir=desc, limit=N)  order and cut
aggregate(op=count|sum|avg, by=col, y=col)  count rows, or sum or avg the number column y; by groups
show(kind=chart|kpi|table, chart=bar|line|pie, title=\"...\", unit=\"...\")  a chart needs aggregate by; a kpi is one total
insert(db:T, set=\"col=value;col=value\")  update(db:T, set=\"col=value\")  delete(db:T)  a write acts on exactly one row the filters find; the person approves it
Example: open todos per status as a bar chart -> get(db:todos) | filter(where=\"status eq open\") | aggregate(op=count, by=status) | show(kind=chart, chart=bar)
Tables:
{catalogue}")
}

/// `"<column> <op> <value>"`: (column, op, value); in and between give a list.
pub fn parse_where(s: &str) -> Result<(String, String, Value), String> {
    let bad = || format!("where {s:?} is not \"<column> <op> <value>\" (op: eq, neq, in, contains, lt, gt, between)");
    let (at, op) = OPS.iter().filter_map(|op| s.find(&format!(" {op} ")).map(|i| (i, *op))).min().ok_or_else(bad)?;
    let (col, val) = (s[..at].trim(), s[at + op.len() + 2..].trim().trim_matches('"'));
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
    p.get(k).and_then(Value::as_str).map(str::to_string)
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
        let errs = d["errors"].as_array().into_iter().flatten().map(|e| e["message"].as_str().unwrap_or("?").to_string()).collect();
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
