# MediKiosk AI Benchmark Protocol

## Purpose

This benchmark is an **engineering evaluation of the current clinical language-understanding layer**. It is intended to make model/rule behavior measurable and reproducible during SIH prototyping.

It is **not** a clinical validation study, diagnostic accuracy study, safety certification, or evidence that the system is fit for autonomous medical decision-making.

## What is evaluated

The current fixed benchmark (`VALIDATION_DATASET_VERSION = 5F.1`) contains 20 synthetic, hand-labelled English utterances covering:

- symptom extraction
- clinical intent/pathway classification
- negation handling
- severity extraction
- duration/time-expression detection

The benchmark evaluates the behavior of `analyze_nlp_text()` on this fixed dataset.

## Metric definitions

### Symptom precision

`TP / (TP + FP)`

Of the symptoms predicted by the system, the proportion that matched the expected positive symptoms.

### Symptom recall

`TP / (TP + FN)`

Of the expected positive symptoms, the proportion detected by the system.

### Symptom F1

The harmonic mean of symptom precision and symptom recall.

### Intent accuracy

The fraction of benchmark cases where the predicted intent exactly matches the hand-labelled expected intent.

### Negation recall

For cases containing explicitly negated symptoms, the fraction of expected negated symptoms correctly represented in the model output.

### Severity accuracy

For cases with an expected severity label, the fraction where the predicted severity exactly matches the expected label.

### Duration detection rate

For cases containing an explicit `for ...` or `since ...` duration expression, the fraction for which at least one duration mention was detected.

## Case-level pass rule

A case passes only when:

1. intent is correct;
2. the complete positive symptom set matches the expected set;
3. all expected negated symptoms are detected; and
4. when severity is labelled, severity is correct.

Duration detection is reported as a metric but is not currently part of the case pass/fail condition. This prevents the benchmark from silently treating an untested dimension as a hard gate.

## Reproducibility

Run the same benchmark through the backend without changing the dataset:

```bash
cd backend
python -m pytest -q
```

The API exposes the same calculation through:

- `GET /api/validation/summary`
- `POST /api/validation/run`

The benchmark dataset is embedded in `main.py` so the exact test inputs used by the endpoint are versioned with the prototype.

## Interpretation rules

A high score on this fixed synthetic set does **not** mean high clinical accuracy. In particular:

- confidence values returned by the NLP layer are not calibrated probabilities;
- a benchmark pass is not a diagnosis or safety guarantee;
- synthetic wording does not represent real-world patient diversity;
- the benchmark does not establish performance across Indian languages;
- the benchmark does not test speech-recognition errors or noisy audio;
- the benchmark does not test unseen hospitals, populations, specialties, or clinical workflows;
- the benchmark is too small to estimate reliable real-world clinical performance.

## Known limitations and bias controls

The current benchmark is deliberately transparent but small. It is vulnerable to overfitting because the cases are hand-authored and live beside the implementation. Results should therefore be treated as **development-set evidence**, not an independent test-set result.

For a stronger future evaluation, maintain a separately versioned holdout set that is not used while changing extraction rules, include paraphrases and realistic spelling/speech-recognition errors, add multilingual and code-switched samples, and have clinical/domain reviewers independently label the cases.

Any future benchmark should report the dataset version and exact evaluation population alongside the metrics so that results from different versions are not compared as though they were the same test.
