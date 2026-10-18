# Manuscript: rate-controllable PPG synthesis for a low-cost simulator

Elsevier `elsarticle` manuscript prepared for *Biomedical Signal Processing and
Control*. The same source can be retargeted to another Elsevier journal by
changing `\journal{...}` in `main.tex`.

| File | Contents |
|---|---|
| `main.tex`, `main.pdf` | Manuscript source and compiled review PDF |
| `refs.bib` | Bibliography; every entry was checked against the publisher, PubMed Central, arXiv, Zenodo, PhysioNet or Mendeley record |
| `highlights.txt` | Five highlights, each under 85 characters (upload as a separate file) |
| `figures/` | Figures 1–7 as PDF (vector, for submission) and PNG (preview), drawn at the 390 pt text width |
| `tables/` | Table bodies generated from the evaluation records; do not edit by hand |
| `make_figures.py` | Builds every figure and table from the evidence files |
| `data/evidence_index.json` | SHA-256 of each evidence file used, plus the numbers quoted in the text |
| `data/measured.json` | New laptop measurements: generator latency and the rate-control curves of Fig. 5 |

## Rebuild

Figures and tables (needs the local Kaggle outputs under `ml/runs/`, which are not in Git):

```bash
PPG_DRY_RUN=1 .venv/bin/python docs/paper/make_figures.py
```

`--no-measure` reuses `data/measured.json` instead of timing the generators again.

PDF (any LaTeX distribution with `elsarticle`; Overleaf works as well):

```bash
cd docs/paper && tectonic main.tex
```

## Before submission

- Replace the author placeholders, affiliation details, e-mail and ORCID iDs in `main.tex` (search for `TODO(authors)`).
- Confirm the CRediT roles, the competing-interest statement and the funding sentence.
- Keep the generative-AI declaration accurate. Elsevier requires it; edit it if the authors' own use of such tools differs.
- Replace the repository URL in the data-availability statement with a release tag or an archived DOI of the submitted version.
- Check the current Guide for Authors of the target journal (word limits, figure formats, cover letter) on the journal website.
- Consider adding a photograph of the assembled bench setup; the paper currently shows CAD renders and a screenshot.

## What the paper does and does not claim

The evaluation is a software and signal-shape evaluation on public datasets. The
optical path (LED driver, chamber, OPT101 receiver) is described but not
validated: the one loopback capture did not reproduce the commanded waveform,
and the paper says so. Raspberry Pi timing comes from software counters, not an
oscilloscope, and the deployed generators were timed on a laptop only. Nothing
in the manuscript is a clinical validation.
