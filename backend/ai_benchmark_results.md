# MediKiosk AI Benchmark Results

## Current benchmark

**Dataset version:** 5F.1  
**Cases:** 20  
**Case pass rate:** 13 / 20 (65.0%)

### Metrics

| Metric | Result |
|---|---:|
| Symptom precision | 100.0% |
| Symptom recall | 69.57% |
| Symptom F1 | 82.05% |
| Intent accuracy | 85.0% |
| Negation recall | 100.0% |
| Severity accuracy | 100.0% |
| Duration detection rate | 100.0% |

### Counts

- True positives: 16
- False positives: 0
- False negatives: 7
- Correct intents: 17 / 20
- Correct expected negations: 3 / 3

## What these results mean

The strongest current result is **precision**: on this fixed synthetic benchmark, every predicted positive symptom matched an expected symptom. Recall is materially lower, meaning the system missed some expected symptoms. The overall case pass rate is 65%, so the prototype should **not** be presented as clinically accurate based on this benchmark.

The results support the narrower statement that the current NLP layer has been subjected to a transparent, repeatable engineering benchmark and that its current strengths and failure areas are measurable.

## What these results do not mean

These numbers are not:

- diagnostic accuracy;
- clinical sensitivity/specificity;
- probability that a patient has a disease;
- evidence that the system is safe to use without clinician review;
- validation of speech recognition;
- validation across Indian languages;
- regulatory or clinical certification.

## Recommended SIH presentation wording

> “We maintain a versioned synthetic benchmark for the prototype NLP layer. On version 5F.1, the current implementation achieves 100% symptom precision, 69.57% symptom recall, 82.05% symptom F1, and 85% intent accuracy. These are engineering benchmark results—not clinical accuracy—and every AI output remains subject to clinician review.”

## Next benchmark maturity step

Before making any claim stronger than engineering validation, create an independent holdout dataset with blinded clinical/domain annotation. The holdout should not be used to tune extraction rules or thresholds, and results should be reported by language, symptom category, negation, severity, duration, and speech/text input mode where applicable.
