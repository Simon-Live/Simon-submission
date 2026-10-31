# Video-quality display fixtures

These are hand-written Part 5 input examples for Part 7's display tests, based on
`../analysis-1.2.0.json`, with additive quality fields illustrated as schema 1.6.0.
They are not model output or evidence that the upstream quality detector has shipped.

- `analysis-none.json`: no `quality` field; the existing result stays unchanged.
- `analysis-minor.json`: a timed recording tip and an unknown future issue code;
  the original score and grade are unchanged.
- `analysis-major.json`: upstream major warnings, an existing warning with a
  framing cause, and an upstream score capped at 59.

Part 7 only displays the supplied impact, text, tip, timestamp and score.
