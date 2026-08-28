# Sources — 56 read, verdicts settled

Verdict = final position after both judges, not the batch reader's grade alone. Where the
reader and a judge disagreed, the final column says who won and why in the line. UNFETCHED =
nobody read it; an unread source is not a rejected one. Reader grades from Judge B's
laundering audit (A/B/C) noted where they change how much to trust the line.

Legend: **adopt** = use as evidence or mechanism · **adapt** = one named piece survives,
the rest refused · **refuse** = nothing survives doctrine · **queued** = adoptable, blocked
on a named precondition · **unknown** = could not be judged from what was fetched.

## Batch 1 (reader grade C — abstract-only)
| Source | Verdict | Why |
|---|---|---|
| Survey of Self-Evolving Agents (arXiv:2507.21046) | adapt | Reading material for doctrine docs; risk is laundering primary self-reports as fact. |
| RSI: Bounded Self-Refinement → Autonomous Loops (arXiv:2607.07663) | adopt | Verification-hierarchy: every rubric declares its verifier's trust tier. Meta-survey, no experiment of its own. |
| EvoLM (arXiv:2605.03871) | refuse | Co-trained rubric+policy: training signal scored by the model being trained (rule 2); needs a training organ nOS refuses. |
| RLAIF (arXiv:2309.00267) | refuse | Same-checkpoint AI feedback (rule 6); kept only as a counter-citation. Load-bearing judge identity unresolved by the reader. |

## Batch 2 (grade B)
| ADAS (arXiv:2408.08435) | adapt | Meta-agent + archive pattern, only with nOS's code oracle; numbers never actually viewed. |
| TextGrad (arXiv:2406.07496) | refuse | Optimization signal is an LLM's own judgment per step (rule 2/6); the apply-an-edit step salvageable under a code judge. |
| LATS (arXiv:2310.04406) | refuse (was adapt) | Judge B: 5–20× calls with no per-step code oracle in existence; the value function is the proposer's own estimate. |
| OPRO (arXiv:2309.03409) | queued (was adopt) | Clean loop shape (code-scored held-out set), but zero sub-1B results — the "fits nos-bi" claim was extrapolation (Judge B §1.7). Revisit after the ops harness measures. |

## Batch 3 (grade A — best read in corpus)
| Promptbreeder (arXiv:2309.16797) | refuse | Fitness scored inside the same model's competence envelope; salvage = replace fitness with a nOS gate, at which point it is not Promptbreeder. |
| STOP (arXiv:2310.02304) | refuse | Improver improves itself, scored by itself, all the way down (rule 2); duplicates the loop's named non-goal. |
| DSPy (arXiv:2310.03714) | adopt | Rejection-sampling bootstrap: keep only traces a CODE metric accepts, use as exemplars. Doctrine-clean if the metric is a nOS gate. |
| ACE paper (arXiv:2510.04618) | adapt — delta-merge only | The append-only structured-delta idea survives; the Reflector/Curator LLM self-write is refused (Batch 3 found the defect itself: a lesson enters permanent context on ONE run's feedback). |

## Batch 4 (grade B)
| EvolveR (arXiv:2510.16079) | adapt | Retrieval-of-principles half only, seeded from judge-approved history — never from self-distillation. |
| Strategy Genes (arXiv:2604.15097) | refuse | Who scores the 4,590 trials is NOT STATED; self-edited failure history unaudited (rule 2). |
| ALMA meta-learned memory (arXiv:2602.07755) | adapt | Structurally the estate's own loop; steal only "memory-retrieval code is a proposable target", scored by nOS gates. |
| A-MEM (arXiv:2502.12110) | refuse | LLM builds/evolves the memory that serves the task it is scored on; and it would be a second copy of unfinished Dreams. |

## Batch 5 (grade B)
| ExpeL (arXiv:2308.10144) | adapt | Insight-write gated on a code-verified verdict row, never self-narrated success. Abstract-only read. |
| MemoryBank (arXiv:2305.10250) | refuse | LLM judges LLM-generated dialogue for "feels personalized" (rule 2). The Ebbinghaus decay arithmetic is a free formula if ever needed. |
| Reflexion (arXiv:2303.11366) | adapt | It is a re-description of AgentKit's existing grader loop; the salvage rule — reflection fires only downstream of a code verdict — is arch item 3. |
| Agentic Harness Engineering (arXiv:2604.25850) | **refuse (was the corpus's only mechanism adopt)** | Judge B's #2 do-not-adopt, upheld: the gates on an agent ARE the files the harness edit touches (rule 4, rule 7). Revisit path = questionnaire Q6(c). |

## Batch 6 (grade A)
| Agent0 (arXiv:2511.16043) | refuse | Reward = the model's own majority vote (rule 2). |
| Debate-Train-Evolve (arXiv:2505.15734) | refuse | Debate agreement stands in for ground truth; echo-chamber convergence risk named. |
| EvoAgent (arXiv:2406.14228) | refuse | LLM binary Retain/Discard as fitness (rule 6); no numbers retrievable in two fetches. |
| SOTOPIA-π (arXiv:2403.08715) | refuse | LLM judges filter training data; authors flag their own judge overestimation; needs a training organ. |

## Batch 7 (grade A)
| Darwin Gödel Machine (arXiv:2505.22954) | adapt — cascade only | The judges' loudest split (B7 adapt vs B13 refuse). Resolved for B13 on the mechanism (self-apply + single-signal selection, rules 5/7/8) and for B7 on the one steal: staged 10→50→200 evaluation. |
| SICA self-improving coder (arXiv:2504.15228) | refuse | The agent's own sub-agents write and run the tests that gate its self-edits (rule 2); n=50 fixed subset sold as SWE-bench Verified. |
| SWE-Gym (arXiv:2412.21139) | adopt | The template: a fixed corpus of verifiable tasks as the contract. Becomes the ops plane's sample-set doctrine. |
| Self-Debug (arXiv:2304.05128) | adapt | Bounded-retry ceiling (~3 turns) where unit tests exist; the Spider no-oracle arm is the cautionary half. |

## Batch 8 (grade C — abstract-only, load-bearing oracle unfetched)
| AutoResearch (arXiv:2608.17906) | refuse | "Independent review" is another LLM call inside the same system (rules 2/6). |
| Frontis-MA1 (arXiv:2607.28568) | adapt — vocabulary only | Draft/Improve/Debug/Crossover as prompt scaffolding; 35B + RL is out of scope. NOTE: the "external Kaggle oracle" rests on an unfetched paper (arXiv:2410.07095). |
| FT-Dojo (arXiv:2603.01712) | refuse | Fine-tuning benchmark, no nOS surface; own-benchmark 10/13 with no seeds. |
| MLEvolve (arXiv:2606.06473) | refuse (was adapt) | Its "Retrospective Memory as Dreams' missing caller" is the exact second-copy-of-unfinished-thing failure (Judge B #1); the AlphaEvolve comparison set is self-selected. |

## Batch 9 (grade B)
| PACEvolve (arXiv:2601.10657) | adapt — context hygiene only | Hierarchical context management (drop stale attempt history from the proposer's prompt); the evolutionary harness is a contract non-goal. |
| AlphaEvolve (arXiv:2506.13131) | adapt — cascade only | Evaluator-executes-h() passes doctrine; the compounding-RSI framing is undemonstrated in its own paper; 100 compute-hours/candidate is another world. |
| Higher-Order Self-Referential Evolution (OpenReview 3tk6AES1Aj) | **UNFETCHED** | Bot wall on OpenReview, Springer paywall on the extension. Unread, not rejected. |
| Economics of RSI (elasticity.institute) | refuse | Self-described first-draft calibration; the 15% threshold is a guessed elasticity read via a search snippet (PDF undecodable). |

## Batch 10 (grade A — the corpus's evidentiary core)
| SAHOO (arXiv:2603.06333) | refuse | Goal Drift Index is a learned detector calibrated inside the loop it polices (rules 2/6); a second, more complex copy of the existing grader. |
| TamperBench (arXiv:2602.06911) | adopt — checklist | One-time reference before ARMING any new local binding. No runtime code. |
| Misevolution (arXiv:2509.26354) | **adopt** | The four-pathway taxonomy; the only source making the estate's refusals legible as design. Zero code. |
| Model collapse / synthetic-data verification (arXiv:2510.16657) | **adopt** | The corpus's strongest result: imperfect verifier sharing the generator's identity plateaus and reverses. Closes `model.grader` (arch item 3). Zero new lines. |

## Batch 11 (grade A)
| Goal drift (arXiv:2505.02709) | **queued** | Best-evidenced new mechanism (20 seeds/condition, action-delta metric, reader-computed). Blocked on one non-failing baseline run — today it would measure the distance between two failures (Judge B §1.5). |
| Introspective awareness (arXiv:2601.01828) | refuse | Needs activation access no nOS adapter has; self-report of internal state is rule 2 shaped anyway. |
| Introspection threshold for RSI (arXiv:2607.04277) | refuse | Theory-by-analogy, no artifact to read (rule 3). |
| Thought-ICS (arXiv:2602.02416) | adapt — oracle arm only | Backtrack-to-last-verified-step, only with a code verifier per step; its own ablation shows the self-verifying arm collapsing. Also: the corpus's only 3B datapoint. |

## Batch 12 (grade A)
| LongWoF-Bench (arXiv:2608.23200) | unknown | PDF streams undecoded; Gene-seeding model overlaps the models re-tested. |
| PostTrainBench (arXiv:2603.08640) | adopt — failure taxonomy | Reward hacking / checkpoint substitution / unauthorized API use as the grep-list for proposer transcripts under bypass conditions. |
| RSI-Bench (github sunghunkwag/rsi-bench) | refuse | An empty scoring shell — caller supplies modify_fn AND evaluate_fn; the single best act of reading in the corpus (core.py opened). |
| RSIBench-Data (arXiv:2607.25886) | **adopt — evidence** | 78.26% of self-continued searches end below peak. Defends the existing ceilings; funds arch item 4. |

## Batch 13 (grade A)
| AgentFactory (github zzatpku) | refuse | Meta-agent is sole arbiter of its own skills' promotion (rules 2/6); the skill-cache idea only under a code save-gate. |
| DGM repo (github jennyzzt/dgm) | refuse | Self-apply + in-process re-run (rules 5/7/8). Cascade already taken via Batch 7. |
| Gödel Agent (github Arvid-pku) | refuse | Runtime monkey-patching collapses the agent-as-auditable-declaration contract (rules 4/5). |
| Hermes Agent (github NousResearch) | refuse | Zero stated oracle; success = adoption metrics the project can market into. **Name collision warning: NOT the estate's Hermes gateway.** |

## Batch 14 (grade B)
| HyperAgents (github facebookresearch) | refuse | Running LLM-generated code per generation is the surface the 24-verb allowlist exists to forbid; no evaluation visible in the README. |
| SEAL (github Continual-Intelligence, arXiv:2506.10943) | refuse | Weights mutating outside a converge (rules 5/7). |
| SIA (github hexo-ai, arXiv:2605.27276) | adapt — nothing to build | Two of three signals are real oracles (H100 timer, MAGIC ground truth); the harness-generation half validates the existing agent-directory design; the weight half refused. |
| ACE repo (github ace-agent/ace) | adapt — delta-merge only | Same resolution as the Batch 3 paper: Batch 3's reading (which found the defect) wins over Batch 8/14's (which recommended the defect). |

## Tallies and the honest bottom line
adopt 8 · adapt 15 · refuse 29 · queued 2 · unknown 1 · UNFETCHED 1.

Of the 8 adopts, **five are evidence or checklists costing zero lines** (2607.07663,
2509.26354, 2510.16657, 2602.06911, 2603.08640's taxonomy, 2607.25886) — the corpus's main
gift is justification for what the estate already refuses. The mechanism adopts are DSPy's
rejection-sampling shape, SWE-Gym's sample-set contract, and the DGM/AlphaEvolve cascade.
For the ops plane at ~1B one-shot, the corpus's honest answer is: **no measurement exists.**
That absence is recorded here as absence, not filled.
