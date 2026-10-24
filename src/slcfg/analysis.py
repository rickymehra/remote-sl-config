"""Heuristics for unknown dumps: ASCII runs, LCD-label candidates and record strides."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .sysex import Message, split_messages

PRINTABLE = range(0x20, 0x7F)
LABEL_LEN = 8  # ReMOTE SL control names are 8 characters on the LCD


@dataclass(frozen=True)
class AsciiRun:
    offset: int
    text: str


def ascii_runs(data: bytes, min_len: int = 3) -> list[AsciiRun]:
    """Maximal runs of printable ASCII with at least one non-space character."""
    runs: list[AsciiRun] = []
    start = None
    for i, b in enumerate([*data, -1]):
        if b in PRINTABLE:
            if start is None:
                start = i
            continue
        if start is not None and i - start >= min_len:
            text = bytes(data[start:i]).decode("ascii")
            if text.strip():
                runs.append(AsciiRun(start, text))
        start = None
    return runs


def label_candidates(data: bytes, length: int = LABEL_LEN) -> list[AsciiRun]:
    """Fixed-width printable fields that look like padded LCD labels.

    A run of exactly ``length`` printable bytes, or a longer run that splits into
    ``length``-sized chunks (labels written back to back), counts.
    """
    out: list[AsciiRun] = []
    for run in ascii_runs(data, min_len=2):
        n = len(run.text)
        if n == length:
            out.append(run)
        elif n > length and n % length == 0 and n <= 6 * length:
            for k in range(0, n, length):
                chunk = run.text[k : k + length]
                if chunk.strip():
                    out.append(AsciiRun(run.offset + k, chunk))
    return out


def stride_scores(data: bytes, lo: int = 4, hi: int = 256) -> list[tuple[int, float]]:
    """Autocorrelation score for each lag in [lo, hi].

    Score = share of positions i where data[i] == data[i+lag], counting only positions
    where at least one of the two bytes is non-zero (zero padding would otherwise match at
    every lag). Sorted best first.
    """
    scores: list[tuple[int, float]] = []
    n = len(data)
    for lag in range(lo, min(hi, n // 2) + 1):
        same = total = 0
        for i in range(n - lag):
            x, y = data[i], data[i + lag]
            if x or y:
                total += 1
                same += x == y
        if total:
            scores.append((lag, same / total))
    # Prefer the smallest lag among near-equal scores (multiples of the true stride tie).
    scores.sort(key=lambda t: (-round(t[1], 3), t[0]))
    return scores


def label_stride(labels: list[AsciiRun]) -> int | None:
    """Most common gap between consecutive label offsets (a second stride estimate)."""
    gaps = Counter(b.offset - a.offset for a, b in zip(labels, labels[1:], strict=False))
    if not gaps:
        return None
    gap, count = gaps.most_common(1)[0]
    return gap if count >= 2 else None


def guess_record_base(labels: list[AsciiRun], stride: int) -> int | None:
    """Offset of the first label that sits on the dominant stride grid."""
    if not labels or stride <= 0:
        return None
    phases = Counter(lab.offset % stride for lab in labels)
    phase = phases.most_common(1)[0][0]
    return min(lab.offset for lab in labels if lab.offset % stride == phase)


@dataclass
class MessageReport:
    index: int
    message: Message
    ascii: list[AsciiRun]
    labels: list[AsciiRun]
    stride: int | None
    stride_score: float | None
    label_stride: int | None
    record_base: int | None


def inspect_bytes(data: bytes, *, max_lag: int = 256) -> list[MessageReport]:
    reports = []
    for i, msg in enumerate(split_messages(data, strict=False)):
        labels = label_candidates(msg.data)
        scores = stride_scores(msg.data, hi=max_lag)
        best = scores[0] if scores else (None, None)
        ls = label_stride(labels)
        stride = ls or best[0]
        reports.append(
            MessageReport(
                index=i,
                message=msg,
                ascii=ascii_runs(msg.data),
                labels=labels,
                stride=best[0],
                stride_score=best[1],
                label_stride=ls,
                record_base=guess_record_base(labels, stride) if stride else None,
            )
        )
    return reports
