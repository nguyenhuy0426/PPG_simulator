# Manuscript: rate-controllable PPG synthesis with a constructed rhythm

Elsevier `elsarticle` manuscript prepared for *Biomedical Signal Processing and
Control*. The same source can be retargeted to another Elsevier journal by
changing `\journal{...}` in `main.tex`.

| File | Contents |
|---|---|
| `main.tex`, `main.pdf` | Manuscript source and compiled review PDF |
| `main.docx` | Word copy for editing, built from the PDF build by `build_docx.py`; the LaTeX source stays the reference |
| `refs.bib` | Bibliography; every entry was checked against the publisher, PubMed Central, arXiv, Zenodo, PhysioNet or Mendeley record |
| `highlights.txt` | Five highlights, each under 85 characters (upload as a separate file) |
| `figures/` | Figures 1–7 as PDF (vector, for submission) and PNG (preview), drawn at the 390 pt text width; Fig. 2 is in Appendix A |
| `tables/` | Table bodies generated from the evaluation records; do not edit by hand |
| `make_figures.py` | Builds every figure and table from the evidence files |
| `make_graphical_abstract.py` | Draws `figures/graphical_abstract.{pdf,png}` (1568 x 627 px at 300 dpi; upload as a separate file) |
| `cover_letter.md` | Draft cover letter to the editor; fill the bracketed fields |
| `make_physigpt_table.py` | Builds `tables/physigpt.tex` (Discussion, network size without a scaffold) from `evidence/physigpt-stage0-v1/results.json` |
| `evidence/` | JSON records of the Kaggle runs the paper uses, copied from `ml/runs/` (which stays local) with the same relative paths |
| `data/evidence_index.json` | SHA-256 of each evidence file used, plus the numbers quoted in the text |
| `data/measured.json` | New laptop measurements: generator latency and the rate-control curves of Fig. 5 |
| `analysis/realism_ci.py`, `data/realism_ci.json` | Subject-bootstrap 95% intervals for the realism table (Tables 5 and 6); reruns the realism evaluation with the same seeds and stops unless it reproduces `evidence/realism-v1/realism_round10.json` |
| `analysis/downstream_detectors.py`, `data/downstream.json` | Beat-detector test (Table 8): NeuroKit2 detectors on real windows with an ECG/Polar reference and on generated strips at the same rates |

## Rebuild

Laptop analyses (run before the figures; both need the data packs under `ml/runs/`, and the detector
test needs NeuroKit2 0.2.10, which the app's environment does not include):

```bash
PPG_DRY_RUN=1 .venv/bin/python docs/paper/analysis/realism_ci.py --threads 8
PPG_DRY_RUN=1 .venv/bin/python docs/paper/analysis/downstream_detectors.py --pylib <directory holding neurokit2>
```

Figures and tables:

```bash
PPG_DRY_RUN=1 .venv/bin/python docs/paper/make_figures.py
```

`--no-measure` reuses `data/measured.json` instead of timing the generators again.
The script reads the run records from `evidence/` and falls back to `ml/runs/` for
any record not copied there. The 49 MB data pack (`ml/runs/physio3-data-v1/physio3_data/windows.npz`,
used for Table 2 and Fig. 4) is not in Git: build it with the Kaggle data kernel
staged by `ml/kaggle_multidomain/stage_kernel.py` and compare its SHA-256 with
`evidence/physio3-data-v1/VERIFICATION.json`. Rerunning the script on unchanged
evidence reproduces every table and figure byte for byte. After a new evaluation
run, copy its JSON record into `evidence/` before rebuilding.

PDF (any LaTeX distribution with `elsarticle`; Overleaf works as well), then the Word copy:

```bash
cd docs/paper && tectonic --keep-intermediates main.tex   # leaves main.bbl next to main.tex
python3 build_docx.py --pandoc <path to pandoc>
```

Edit `main.tex`, not `main.docx`: the Word file is for reading and commenting, and changes made there have to be
carried back into the LaTeX source by hand.

## Before submission

- Replace the author placeholders, affiliation details, e-mail and ORCID iDs in `main.tex` (search for `TODO(authors)`).
- Confirm the CRediT roles, the competing-interest statement and the funding sentence.
- Revise the text yourselves. Elsevier's journal policy (updated June 2026) allows AI-drafted text only
  with genuine intellectual contribution and review by the authors; complete the oversight sentence of
  the AI declaration, which must stay immediately before the references, and describe any AI help with
  the software, the boards or the experiments in the Methods.
- The frozen rules and records of steps B–E (`docs/physioflow/rules`, `docs/physioflow/loop`) and the PPG-physiGPT
  runs (`docs/physigpt`) are on `main` (1 Nov 2026); confirm that the PhysioFlow-SB code of Tables 4 and 5 is there
  as well before tagging the release.
- Push, tag the submitted version and archive it (for example on Zenodo); cite that tag or DOI in the
  data-availability statement.
- "Low-cost" was dropped from the title and the text. If you want it back, support it with a component cost
  (actual purchase prices).
- Time the deployed generators on the Pi with `scripts/verify_generators_on_pi.py` (same protocol as
  Table 1; see `docs/hardware-validation/README.md`) and replace the statements that they were not
  timed on the Pi (Sections 5.7 and 6.2, the limitations and Appendix A).
- The paper is now centred on the generators; the simulator hardware, its timing counters and the failed
  optical loopback are in Appendix A. Once the optical path is validated, extend Appendix A (or move it back
  into the main text) with the measured waveform.
- `main.pdf` is a reading copy without line numbers. If the journal asks for line-numbered review
  manuscripts, set `\reviewtrue` near the top of `main.tex` and rebuild.
- Check the current Guide for Authors of the target journal (word limits, figure formats, cover letter) on
  the journal website. The abstract limit is 250 words; the paper gives six keywords.
- Consider adding a photograph of the assembled bench setup; the paper currently shows CAD renders and a screenshot.
- Rebuild `main.pdf` (Tectonic or Overleaf) after the last edits: the PDF in this folder predates the related-work
  table, the statistical-analysis section, the ethics statement, the abbreviations appendix and the
  network-size subsection.
- Upload separately: `highlights.txt`, `figures/graphical_abstract.pdf`, the cover letter (PDF), and the figures.

## What the paper does and does not claim

The evaluation is a software and signal-shape evaluation on public datasets. The
optical path (LED driver, chamber, OPT101 receiver) is described but not
validated: the one loopback capture did not reproduce the commanded waveform,
and the paper says so. Raspberry Pi timing comes from software counters, not an
oscilloscope, and the deployed generators were timed on a laptop only. Nothing
in the manuscript is a clinical validation.
