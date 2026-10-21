# Agent Refinement Log: <agent-name>
**Started:** YYYY-MM-DD  
**Baseline:** eval_pass_rate=XX%, dispatch_accuracy=XX%, resilience=X.X/10, project_fit=X.X/10  
**Target:** eval_pass_rate ≥ 80%, dispatch_accuracy ≥ 85%, resilience_score ≥ 8/10  
**Training set:** <N> failing scenarios from refine-input.json (adversarial always included)  
**Held-out set:** project-native, project-workflow, multi-turn scenarios  

## Iterations

### Iteration 1
- **Hypothesis:** Changing [section] will improve [scenario name] because [reason]
- **Lever:** A/B/C/D/E — [what type of change]
- **Change:** [one-line summary]
- **Before:** eval_pass_rate=XX%, dispatch_accuracy=XX%, resilience=X.X/10
- **After:** eval_pass_rate=XX%, dispatch_accuracy=XX%, resilience=X.X/10
- **Agent-audit:** PASS / BLOCK (if Lever E — always run)
- **Size:** XXXX → XXXX bytes (`wc -c` of the edited file, before → after)
- **Decision:** KEPT / REVERTED / NEUTRAL-KEPT / NEUTRAL-REVERTED
- **Note:** [why it worked or didn't]

## Final Results

| Metric | Baseline | Final | Delta |
|--------|----------|-------|-------|
| Eval Pass Rate | XX% | XX% | +/-XX% |
| Dispatch Accuracy | XX% | XX% | +/-XX% |
| Resilience Score | X.X/10 | X.X/10 | +/-X.X |
| Project Fit Score | X.X/10 | X.X/10 | +/-X.X |
| Context Footprint | XXL | XXL | +/-XXL |
| Iterations run | — | N | — |
| Keep rate | — | X/N | — |

**Levers used:** A(N), B(N), C(N), D(N), E(N)  
**Most effective lever:** [letter] — [what worked]  
**Failed hypotheses:** [list — data for future sessions]  

**Recommendation:** DONE / NEEDS-REWRITE / CONTINUE / RE-ADAPT
