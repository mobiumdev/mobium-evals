# Claims with known answers

A suite for judging a verifier: claims about recorded Morpho Match runs
([mobiumdev/morpho-match](https://github.com/mobiumdev/morpho-match)), each with an answer settled by a deterministic fact —
a passing or failing assertion, a pinned deal, a bug known to be on —
never by someone reading a screen.

- `build_claims.py` writes `claims.json` and refuses to if any claim's
  ground truth does not hold: a true claim's test must have passed in its
  run, a false claim's test must have failed there, at the assertion that
  settles it.
- `score.py results/<run>.json` scores a judge's verdicts against it.
- `results/` holds each judge's verdicts.

The recordings (`recordings/`, ~100 MB, not in git) are
`mobium test --trace on` over Morpho Match's `tests/match.test.json`, once
clean and once with each bug on:

```sh
EVALS=$PWD                      # this repository's root
cd <a checkout of morpho-match>
for b in none score-double pair-never best-lost sort-three; do
  mobium open "morphomatch://bugs?off=all"
  [ $b = none ] || mobium open "morphomatch://bugs?on=$b"
  mobium test --config tests/mobium.config.json --trace on --reporter list \
    --output $EVALS/claims/recordings/$b > $EVALS/claims/recordings/$b.txt 2>&1
done
mobium open "morphomatch://bugs?off=all"
python3 $EVALS/claims/build_claims.py
```

## Results

28 claims: 15 passed, 10 failed, 3 inconclusive. Sixteen settled by text on
a recorded screen; twelve harder (`HARD` in `build_claims.py`), settled
from the app's source, the test file or the recording: a color only the
screenshot shows, a moment the recording never caught, every card tapped
once, the tray's order before any drag.

| Date | Judge | Right | Confidently wrong |
| --- | --- | --- | --- |
| 2026-10-25 | Claude Code subagents through `mobium recording` + `mobium verdict` (no API key; three judges, four harder claims each, plus the first 16) | **28 / 28** | 0 |
| 2026-10-25 | `mobium check --model openai:qwen2.5:14b` (Ollama) | **17 / 28** | 0 |
| 2026-10-25 | `mobium check --model openai:mistral-small:24b` (Ollama) | **13 / 28** | **6** (5 false claims passed) |
| 2026-10-25 | `openai:nvidia/nemotron-3-ultra-550b-a55b:free` (OpenRouter, free tier), **six claims only**: mistral's wrong ones | **6 / 6** | 0 |

What it says:
- **A judge is useful when it is never confidently wrong.** qwen is safe
  but timid: every miss is inconclusive. mistral passed five false claims,
  twice with a summary saying the opposite ("Card 3 turned out to be the
  Blue Morpho, not the Monarch" — for the claim that it was the Monarch):
  it judges what happened, not the claim. Its citations were real, so the
  citation rule could not catch it. **A cited verdict is not a true one.**
- The local models are never shown a screenshot (Ollama's chat API takes
  images only in user turns). qwen still failed the orange-card claim,
  from the card's name, not its color.
- The subagents are the same model family as the claim writer; not an
  independent judge.
- Two harness defects shaped the first local runs and are fixed in Mobium
  (mobiumdev/mobium#281): a model answering in prose is asked again for
  its verdict, and a citation in a key the schema has not got is refused
  by name. qwen's first run, before them, was 15 / 28.
- The prefix was `local:` when these ran (Mobium renamed it `openai:`
  the same day), so the results files keep `local-` in their names.
- OpenRouter's free tier gives 50 free-model requests a day; a claim takes
  6–10. The rest of Nemotron's 28 takes about three more days at $0.
