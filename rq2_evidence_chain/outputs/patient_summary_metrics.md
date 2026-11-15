# H3: patient summaries

Unsupported = P(supported) below the threshold. Lower is better for unsupported counts and reading grade.

## va_test

| summary built from | cases | unsupported vs signed note | unsupported vs dialogue | next-step recall | reading grade (FK) | sentences |
|---|---|---|---|---|---|---|
| verified (signed note + checker) | 110 | 0.0 | 0.7364 | 0.9142 | 7.178 | 6.8636 |
| unverified record, no checker | 110 | 0.5455 | 1.3545 | 0.9034 | 6.7188 | 7.2364 |

Checker dropped 0.2727 draft sentence(s) per summary.

## all_cases

| summary built from | cases | unsupported vs signed note | unsupported vs dialogue | next-step recall | reading grade (FK) | sentences |
|---|---|---|---|---|---|---|
| verified (signed note + checker) | 136 | 0.0 | 0.7647 | 0.9177 | 7.0893 | 6.9853 |
| unverified record, no checker | 136 | 0.5221 | 1.3603 | 0.9076 | 6.7111 | 7.4412 |

Checker dropped 0.2574 draft sentence(s) per summary.
