/**
 * corpus-gen — synthesise cortex-lang chains and keep the ones the validator accepts.
 *
 * WHY THIS IS AN UNUSUALLY CHEAP THING TO BUILD, and the roadmap row
 * (`local-llm-corpus`) says so in one line: *the opcode registry and the
 * validator are a free oracle*. Most fine-tuning projects have no way to tell a
 * good sample from a bad one without a human or a large model. Here a chain is
 * well-formed or it is not, and `analyzeCortex` — pure, no store, no network —
 * says which. So the correctness filter costs nothing and the teacher runs zero
 * times.
 *
 * WHAT IT ANSWERS FIRST, before anyone trains anything. The row asks for the
 * size of the space, because that is what decides whether a small model is
 * worth training at all: a grammar with a few hundred distinguishable shapes is
 * a lookup table, one with millions is a language. This prints that number from
 * enumeration rather than estimating it.
 *
 * DETERMINISTIC BY CONSTRUCTION. No RNG. Stages are enumerated in registry
 * order and chains in odometer order, so two runs of the same registry emit
 * byte-identical corpora — which is what makes a corpus a fixture you can diff
 * rather than a sample you have to trust.
 *
 * THE PURE HALF ONLY. `analyzeCortex` decides grammar and structure; it does
 * NOT resolve operands (that is `cortex-resolve`, which needs the store). So a
 * chain here is *well-formed*, never *runnable* — `tax:01.01` is legal shape
 * whether or not that node exists. Saying otherwise would be the corpus
 * claiming a resolution it never performed.
 *
 * NOT DONE HERE, deliberately: the back-translation half of the row ("have a
 * large model write the sentence a user would have said"). That needs a model,
 * which makes it a different kind of job with a different cost — this half
 * needs nothing and is the input to it.
 *
 * Usage:
 *   npx tsx scripts/corpus-gen.ts                    # summary to stdout
 *   npx tsx scripts/corpus-gen.ts --max-stages 3     # deeper chains
 *   npx tsx scripts/corpus-gen.ts --out corpus.jsonl # write the valid chains
 *   npx tsx scripts/corpus-gen.ts --json             # summary as JSON
 */
import { writeFileSync } from "node:fs";

import { analyzeCortex, CORTEX_SOURCES } from "../server/cortex-lang";
import { CORTEX_OPCODES, type CortexNamespace } from "../server/cortex-opcodes";

/**
 * One representative operand per namespace.
 *
 * A REPRESENTATIVE, NOT A CATALOGUE. The pure validator checks the SHAPE of an
 * operand and never asks whether the resource exists, so a second `db:` sample
 * would multiply the corpus without adding a distinguishable form. The one
 * place shape genuinely varies is the `[label]` suffix, which is why `tax:`
 * carries both spellings.
 */
const OPERAND: Readonly<Record<CortexNamespace, readonly string[]>> = {
  tax: ["tax:01.01", "tax:01.01[Kinematics]"],
  ent: ["ent:person"],
  kg: ["kg:node"],
  // Dashes, not underscores: REL_VERB_RE is /^[a-z][a-z0-9-]{0,63}$/.
  // `rel:depends_on` was the first sample and the validator refused it,
  // which is the generator earning its keep before it generated anything.
  rel: ["rel:depends-on"],
  db: ["db:products"],
  svc: ["svc:wing"],
  doc: ["doc:readme"],
  agent: ["agent:surveyor"],
};

/** One value per declared param type. Same reasoning as OPERAND. */
const PARAM_VALUE: Readonly<Record<string, string>> = {
  int: "3",
  bool: "true",
  string: '"x"',
};

interface Stage {
  readonly text: string;
  readonly opcode: string;
}

/**
 * Every distinguishable form of one opcode: with and without an operand where
 * the arity allows both, and with each declared param in turn.
 *
 * Params are offered ONE AT A TIME rather than in every combination. The
 * combinatorics of the full power set buy shapes a model has no trouble
 * generalising to (`limit=3, fields="x"` teaches nothing `limit=3` did not),
 * and they are what turns a readable corpus into an unreadable one.
 */
function stagesFor(op: (typeof CORTEX_OPCODES)[number]): Stage[] {
  const out: Stage[] = [];
  const push = (text: string) => out.push({ text, opcode: op.name });

  const operands: string[] = [];
  if (op.operands.min === 0) operands.push("");
  for (const ns of op.operands.namespaces) {
    for (const sample of OPERAND[ns as CortexNamespace] ?? [])
      operands.push(sample);
  }

  for (const operand of operands) {
    push(`${op.name}(${operand})`);
    for (const [param, spec] of Object.entries(op.params ?? {})) {
      const value = PARAM_VALUE[(spec as { type: string }).type];
      if (value === undefined) continue;
      const args = operand
        ? `${operand}, ${param}=${value}`
        : `${param}=${value}`;
      push(`${op.name}(${args})`);
    }
  }
  return out;
}

interface Summary {
  registryOpcodes: number;
  stagesEnumerated: number;
  chainsTried: number;
  chainsValid: number;
  chainsRejected: number;
  maxStages: number;
  /** Opcodes that produced no valid chain at all — the interesting column. */
  opcodesWithoutAValidChain: string[];
  rejectionsByCode: Record<string, number>;
  /**
   * MEASURED 2026-08-29 and it is the headline, not a footnote: at depth 2,
   * 20 306 of 20 306 composed chains validate. The pure analyzer rejects
   * STAGE-LOCAL faults (unknown opcode, unknown param, arity) and imposes no
   * compositional rule whatever — `insert | classify` and `classify | insert`
   * both pass, `rank()` four times passes. So "the validator is a free
   * oracle" is true about syntax and false about sense, and a corpus filtered
   * only on validity is a grammar drill.
   *
   * The warnings are the only thing here that discriminates between chains, so
   * they are counted and printed beside the useless zero.
   */
  warningsByCode: Record<string, number>;
  validRate: string;
}

function main(argv: string[]): number {
  const maxStages = Number(valueOf(argv, "--max-stages") ?? 2);
  const out = valueOf(argv, "--out");
  const asJson = argv.includes("--json");
  if (!Number.isInteger(maxStages) || maxStages < 1 || maxStages > 4) {
    // 4 is not arbitrary: the odometer is |stages|^n and |stages| is in the
    // hundreds, so 5 is minutes of enumeration for shapes nothing will read.
    console.error("--max-stages must be an integer in 1..4");
    return 2;
  }

  const stages = CORTEX_OPCODES.flatMap(stagesFor);
  const valid: string[] = [];
  const rejectionsByCode: Record<string, number> = {};
  const warningsByCode: Record<string, number> = {};
  const producedValid = new Set<string>();
  let tried = 0;

  for (let depth = 1; depth <= maxStages; depth++) {
    for (const combo of odometer(stages, depth)) {
      // `@input` only. The other four sources (`@user`, `@ctx`, `@sel`,
      // `@prev`) are the same grammar with a different head, so including them
      // would multiply the corpus by five and teach one token.
      const text = `@input | ${combo.map((s) => s.text).join(" | ")}`;
      tried++;
      const analysis = analyzeCortex(text);
      if (analysis.errors.length === 0) {
        valid.push(text);
        for (const s of combo) producedValid.add(s.opcode);
        for (const w of analysis.warnings) {
          warningsByCode[w.code] = (warningsByCode[w.code] ?? 0) + 1;
        }
      } else {
        const code = analysis.errors[0].code;
        rejectionsByCode[code] = (rejectionsByCode[code] ?? 0) + 1;
      }
    }
  }

  const summary: Summary = {
    registryOpcodes: CORTEX_OPCODES.length,
    stagesEnumerated: stages.length,
    chainsTried: tried,
    chainsValid: valid.length,
    chainsRejected: tried - valid.length,
    maxStages,
    opcodesWithoutAValidChain: CORTEX_OPCODES.map((o) => o.name).filter(
      (n) => !producedValid.has(n),
    ),
    rejectionsByCode,
    warningsByCode,
    validRate:
      tried === 0 ? "n/a" : `${((valid.length / tried) * 100).toFixed(1)}%`,
  };

  if (out) {
    writeFileSync(
      out,
      valid.map((c) => JSON.stringify({ chain: c })).join("\n") + "\n",
    );
  }
  if (asJson) {
    console.log(JSON.stringify(summary, null, 2));
    return 0;
  }

  console.log(
    `cortex-lang corpus — ${CORTEX_SOURCES.length} sources, @input enumerated`,
  );
  console.log(`  registry            ${summary.registryOpcodes} opcodes`);
  console.log(`  stage forms         ${summary.stagesEnumerated}`);
  console.log(
    `  chains tried        ${summary.chainsTried} (depth 1..${maxStages})`,
  );
  console.log(`  chains VALID        ${summary.chainsValid}`);
  console.log(
    `  chains rejected     ${summary.chainsRejected}  (${summary.validRate} valid)`,
  );
  if (summary.chainsRejected === 0 && maxStages > 1) {
    console.log(
      "  NOTE: nothing composed was rejected. The analyzer constrains",
    );
    console.log(
      "        STAGES, not their ORDER — so validity is not selectivity",
    );
    console.log(
      "        here, and a corpus filtered on it teaches grammar only.",
    );
  }
  for (const [code, n] of Object.entries(summary.warningsByCode).sort(
    (a, b) => b[1] - a[1],
  )) {
    console.log(`    warned   ${String(n).padStart(6)}  ${code}`);
  }
  if (summary.opcodesWithoutAValidChain.length) {
    // The column worth reading: an opcode the generator cannot express is
    // either a gap in OPERAND above or an opcode nothing can legally call.
    console.log(
      `  no valid chain for  ${summary.opcodesWithoutAValidChain.join(", ")}`,
    );
  }
  for (const [code, n] of Object.entries(rejectionsByCode).sort(
    (a, b) => b[1] - a[1],
  )) {
    console.log(`    rejected ${String(n).padStart(6)}  ${code}`);
  }
  if (out) console.log(`  wrote               ${out}`);
  return 0;
}

/** Deterministic n-tuples, registry order, no RNG. */
function* odometer<T>(items: readonly T[], depth: number): Generator<T[]> {
  const idx = new Array(depth).fill(0);
  for (;;) {
    yield idx.map((i) => items[i]);
    let k = depth - 1;
    while (k >= 0 && ++idx[k] === items.length) idx[k--] = 0;
    if (k < 0) return;
  }
}

function valueOf(argv: string[], flag: string): string | undefined {
  const i = argv.indexOf(flag);
  return i >= 0 ? argv[i + 1] : undefined;
}

process.exit(main(process.argv.slice(2)));
