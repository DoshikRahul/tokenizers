"""Statistics: encounter-clustered paired bootstrap, exact McNemar, Holm correction, ROC AUC."""
import math
import random
from typing import Callable, Dict, List, Sequence


def cluster_bootstrap_diff(rows_a: Dict[str, bool], rows_b: Dict[str, bool], cluster_of: Dict[str, str],
                           n_boot=2000, seed=42):
    """Paired difference of means (b - a) over the same statement ids, resampling encounters."""
    ids = [i for i in rows_a if i in rows_b]
    if not ids:
        return dict(diff=float("nan"), lo=float("nan"), hi=float("nan"), n=0)
    clusters: Dict[str, List[str]] = {}
    for i in ids:
        clusters.setdefault(cluster_of[i], []).append(i)
    keys = list(clusters)

    def stat(sample_ids):
        return (sum(rows_b[i] for i in sample_ids) - sum(rows_a[i] for i in sample_ids)) / max(1, len(sample_ids))

    point = stat(ids)
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        s = []
        for _ in keys:
            s.extend(clusters[rng.choice(keys)])
        boots.append(stat(s))
    boots.sort()
    return dict(diff=point, lo=boots[int(0.025 * n_boot)], hi=boots[int(0.975 * n_boot) - 1], n=len(ids))


def bootstrap_ci(values: Dict[str, bool], cluster_of, n_boot=2000, seed=42):
    ids = list(values)
    clusters: Dict[str, List[str]] = {}
    for i in ids:
        clusters.setdefault(cluster_of[i], []).append(i)
    keys = list(clusters)
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        s = [x for _ in keys for x in clusters[rng.choice(keys)]]
        boots.append(sum(values[i] for i in s) / max(1, len(s)))
    boots.sort()
    return boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1]


def mcnemar_exact(a: Dict[str, bool], b: Dict[str, bool]):
    """Two-sided exact McNemar on paired binary outcomes."""
    ids = [i for i in a if i in b]
    n01 = sum((not a[i]) and b[i] for i in ids)
    n10 = sum(a[i] and (not b[i]) for i in ids)
    n = n01 + n10
    if n == 0:
        return dict(b_only=n01, a_only=n10, p=1.0)
    k = min(n01, n10)
    p = sum(math.comb(n, j) for j in range(0, k + 1)) / 2 ** n
    return dict(b_only=n01, a_only=n10, p=min(1.0, 2 * p))


def holm(pvals: Dict[str, float]) -> Dict[str, float]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, out, running = len(items), {}, 0.0
    for r, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - r) * p))
        out[k] = running
    return out


def roc_auc(scores_pos: Sequence[float], scores_neg: Sequence[float]) -> float:
    """P(score_pos > score_neg) with ties = 0.5 (Mann-Whitney)."""
    if not scores_pos or not scores_neg:
        return float("nan")
    allv = sorted([(s, 1) for s in scores_pos] + [(s, 0) for s in scores_neg])
    rank_sum, i, n = 0.0, 0, len(allv)
    while i < n:
        j = i
        while j + 1 < n and allv[j + 1][0] == allv[i][0]:
            j += 1
        avg = (i + j) / 2 + 1
        rank_sum += avg * sum(1 for t in range(i, j + 1) if allv[t][1] == 1)
        i = j + 1
    npos, nneg = len(scores_pos), len(scores_neg)
    return (rank_sum - npos * (npos + 1) / 2) / (npos * nneg)
