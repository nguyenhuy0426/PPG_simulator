<!-- TODO(authors): fill the bracketed fields, sign, and export to PDF for the submission system. -->

[Date]

The Editor-in-Chief
*Biomedical Signal Processing and Control*

Dear Editor,

We submit the manuscript **"Rate-controllable PPG synthesis for a low-cost simulator: rhythm-scaffolded GAN and
rectified flow under pre-registered evaluation"** for consideration as a Research Paper.

Bench simulators let developers test photoplethysmogram (PPG) algorithms and optical front-ends without recruiting
subjects, but the parametric pulses they play back are easily told apart from recorded PPG, and generative models of
PPG do not follow an operator's rate command. The manuscript addresses both problems in one open system:

- a Raspberry Pi 4 simulator with two 12-bit converters and a red/infrared LED driver, whose real-time output was
  measured on the device;
- two generators, a conditional GAN and a conditional rectified-flow model, that construct the beat sequence from
  the commanded rate and irregularity and learn only the waveform, giving a mean rate error below 1 bpm from 40 to
  180 bpm;
- an evaluation in which every model-selection rule was fixed and hashed before training, with realism measured on
  subjects never used for training by a subject-grouped classifier two-sample test, a frozen PPG foundation model,
  recording-context classification and memorisation screening.

We report negative results as fully as positive ones: neither generator transferred to everyday wrist PPG from an
unseen device, the pre-registered rules twice kept the deployed model unchanged, and a three-times-larger pretrained
transformer did not close the remaining high-frequency gap. We believe this combination of hardware, rate-exact
generation and pre-registered, subject-disjoint evaluation fits the journal's scope in biomedical signal
processing, measurement and instrumentation.

All data are public and de-identified; code, board designs, trained models, frozen decision rules and the evaluation
records that produce every figure and table are available at https://github.com/nguyenhuy0426/PPG_simulator
([archive DOI of the submitted version]).

This manuscript has not been published and is not under consideration elsewhere. All authors have approved the
submission and declare no competing interests. The use of AI-assisted tools in preparing the manuscript is declared
in the manuscript, as required by the journal's policy.

Sincerely,

[Corresponding author name], on behalf of all authors
[Affiliation]
[E-mail] · [ORCID]
