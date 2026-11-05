#!/usr/bin/env bash
# Two Kaggle T4 x2 sessions from the account the Kaggle CLI is logged in as (default charlesday2612):
#   psf     PSF-GAN, the pure GAN (ml/kaggle_physigpt/pure_gan.py), heart-rate conditioned
#   apft    APFT-GAN v3 (ml/kaggle_physigpt/gan.py) from the V1 large release, heart-rate conditioned
# Both mount the MIMIC-III shards and the V1 release of SOURCE_OWNER (default halovie2412), which must be shared
# with OWNER on Kaggle. Each kernel trains, then scores its best checkpoint on the 180 held-out people
# (eval/summary.json: mean similarity in %, per feature, tree accuracy, strict-judge AUC).
#
# Usage (from the repository root, on a claude/model-benchmark-* branch, with `kaggle` logged in):
#   scripts/kaggle_two_sessions.sh push [psf|apft|both]   stage and push the kernels (default both)
#   scripts/kaggle_two_sessions.sh status                 status of both kernels
#   scripts/kaggle_two_sessions.sh pull                   download the outputs of finished kernels
#   scripts/kaggle_two_sessions.sh report                 print both eval/summary.json side by side
#   scripts/kaggle_two_sessions.sh wait                   status every 10 min until both end, then pull + report
#
# The Kaggle CLI is found on PATH, in ~/.local/bin, in a .venv/venv of this worktree or of the main checkout, or in
# conda; otherwise give it: KAGGLE=/path/to/kaggle scripts/kaggle_two_sessions.sh push
#
# Settings by environment: OWNER, SOURCE_OWNER, OUT (default runs/kaggle), PSF_EXTRA and APFT_EXTRA (extra options of
# pure_gan.py / gan.py as one string), STRICT_SEEDS (strict-judge seeds of the evaluation, default "0").
set -euo pipefail

OWNER=${OWNER:-charlesday2612}
SOURCE_OWNER=${SOURCE_OWNER:-halovie2412}
OUT=${OUT:-runs/kaggle}
STRICT_SEEDS=${STRICT_SEEDS:-0}
# PSF-GAN: 256 windows per T4 and step; the time budget and --patience end it, the lr decay follows the time budget
PSF_EXTRA=${PSF_EXTRA:---hr-cond --batch 256 --eval-every 2000 --patience 10}
# APFT-GAN v3: --steps is a ceiling; --patience 8 at --eval-every 250 stops after 2000 steps without a new best
APFT_EXTRA=${APFT_EXTRA:---hr-cond}
PSF_TAG=psf-gan
APFT_TAG=apft-gan-v3-hr
COMMON=(--owner "$OWNER" --source-owner "$SOURCE_OWNER" --stage 0 --shards 1 2 3 4 --solos 0
        --datasets ppg-physigpt-shard0-data-v1 --strict-seeds $STRICT_SEEDS)

slug() { echo "$OWNER/ppg-physigpt-$1-v1"; }

# The Kaggle CLI: $KAGGLE if set, else `kaggle` on PATH, else the usual install places (user bin, a venv of this
# worktree or of the main checkout, conda), else the kaggle module of python3.
find_kaggle() {
  local main c
  if [[ -n ${KAGGLE:-} ]]; then echo "$KAGGLE"; return; fi
  if type -P kaggle >/dev/null; then type -P kaggle; return; fi   # a path only: kaggle() below is a function
  main=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null | sed 's#/\.git$##')
  for c in "$HOME/.local/bin/kaggle" "$HOME/.venvs/kaggle/bin/kaggle" ./.venv/bin/kaggle ./venv/bin/kaggle "${main:-.}/.venv/bin/kaggle" \
           "${main:-.}/venv/bin/kaggle" "${CONDA_PREFIX:-/nonexistent}/bin/kaggle" "$HOME"/miniconda3/bin/kaggle \
           "$HOME"/anaconda3/bin/kaggle; do
    if [[ -x $c ]]; then echo "$c"; return; fi
  done
  # find_spec, not import: importing kaggle authenticates and prints
  if python3 -c "import importlib.util as u, sys; sys.exit(u.find_spec('kaggle') is None)" >/dev/null 2>&1; then echo "python3 -c 'import sys; from kaggle.cli import main; sys.argv[0]=\"kaggle\"; main()'"; return; fi
  return 1
}

kaggle() { eval "$KAGGLE_CMD" '"$@"'; }

need_kaggle() {
  KAGGLE_CMD=$(find_kaggle) || {
    echo "kaggle CLI not found. Find it with: which -a kaggle; pip show kaggle (Location), ls ~/.local/bin"
    echo "then run: KAGGLE=/path/to/kaggle $0 ${ARGS[*]}"
    exit 1
  }
  case $KAGGLE_CMD in python3*) ;; *) KAGGLE_CMD=$(printf '%q' "$KAGGLE_CMD") ;; esac
  echo "kaggle CLI: $KAGGLE_CMD"
  kaggle kernels list --mine --page-size 1 >/dev/null || { echo "kaggle CLI is not logged in (kaggle auth login)"; exit 1; }
}

stage_psf() {
  python3 -m ml.kaggle_physigpt.stage "$OUT/$PSF_TAG" puregan "${COMMON[@]}" --tag "$PSF_TAG" \
    --gan-extra="$PSF_EXTRA" >/dev/null
}

stage_apft() {
  python3 -m ml.kaggle_physigpt.stage "$OUT/$APFT_TAG" gan "${COMMON[@]}" --config large \
    --from-slug ppg-physigpt-decay0-large-v1 --tag "$APFT_TAG" --gan-steps 20000 --eval-every 250 --patience 8 \
    --gen-steps 16 --gan-extra="$APFT_EXTRA" >/dev/null
}

push() {
  need_kaggle
  local which=${1:-both}
  mkdir -p "$OUT"
  if [[ $which == psf || $which == both ]]; then
    stage_psf && kaggle kernels push -p "$OUT/$PSF_TAG"
  fi
  if [[ $which == apft || $which == both ]]; then
    stage_apft && kaggle kernels push -p "$OUT/$APFT_TAG"
  fi
}

status() {
  need_kaggle
  for tag in "$PSF_TAG" "$APFT_TAG"; do
    printf '%-28s ' "$tag"; kaggle kernels status "$(slug "$tag")" 2>&1 | tail -1
  done
}

pull() {
  need_kaggle
  for tag in "$PSF_TAG" "$APFT_TAG"; do
    if kaggle kernels status "$(slug "$tag")" 2>&1 | grep -qiE 'complete|error|cancel'; then
      mkdir -p "$OUT/$tag/output"
      kaggle kernels output "$(slug "$tag")" -p "$OUT/$tag/output" --force >/dev/null && echo "pulled $tag"
    else
      echo "$tag is still running"
    fi
  done
}

report() {
  python3 - "$OUT" "$PSF_TAG" "$APFT_TAG" <<'PY'
import json, sys
from pathlib import Path
out, tags = Path(sys.argv[1]), sys.argv[2:]
rows = {}
for tag in tags:
    found = sorted((out/tag/"output").rglob("eval/summary.json"))
    if not found:
        print(f"{tag}: no eval/summary.json yet (run pull after the kernel ends; see its log for errors)")
        continue
    rows[tag] = json.loads(found[0].read_text())
    gan = sorted((out/tag/"output").rglob("gan/gan_summary.json"))
    if gan:
        g = json.loads(gan[0].read_text())
        print(f"{tag}: {g.get('steps')} steps, {g.get('hours', 0):.2f} h, stop: {g.get('stop_reason')}, "
              f"best step {g.get('best', {}).get('step')}")
if rows:
    ref = next(iter(rows.values()))
    print(f"\n{'':24}" + "".join(f"{t:>18}" for t in rows) + f"{'real vs real':>16}")
    print(f"{'mean similarity %':24}" + "".join(f"{r['mean_similarity_percent']:>18}" for r in rows.values())
          + f"{ref['real_vs_real_percent']:>16}")
    print(f"{'tree accuracy':24}" + "".join(f"{r['tree_accuracy']:>18.3f}" for r in rows.values()) + f"{0.5:>16}")
    print(f"{'strict judge AUC':24}" + "".join(f"{r.get('strict_judge_auc', float('nan')):>18.3f}" for r in rows.values()))
    print(f"{'verdict':24}" + "".join(f"{r['verdict']:>18}" for r in rows.values()))
    for k in ref["feature_percent"]:
        print(f"{k:24}" + "".join(f"{r['feature_percent'][k]:>18}" for r in rows.values())
              + f"{ref['real_vs_real_feature_percent'][k]:>16}")
    print("\ntarget: mean >= 95 %, every feature >= 90 % (or its real-vs-real value), tree accuracy <= 0.60")
PY
}

wait_all() {
  while status | grep -qiE 'running|queued'; do sleep 600; done
  pull && report
}

ARGS=("$@")
case ${1:-} in
  push) push "${2:-both}" ;;
  status) status ;;
  pull) pull ;;
  report) report ;;
  wait) wait_all ;;
  *) sed -n '2,20p' "$0"; exit 1 ;;
esac
