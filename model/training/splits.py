"""Leakage-aware train/validation/test splitting.

RDD2022 has no sequence metadata. Its images are numbered per country in
capture order, so neighbouring numbers are often neighbouring video frames of
the same stretch of road. Images are therefore split in groups, never singly:

* a group is a block of consecutive image numbers from one source;
* byte-identical images are merged into one group;
* a whole source can be held out as the test set.

This removes most near-duplicate leakage. It cannot prove that two different
blocks never show the same road.
"""
import random
import re
from collections import defaultdict
from dataclasses import dataclass

SPLITS = ("train", "val", "test")
_NUMBERED = re.compile(r"^(?P<source>.+?)_(?P<index>\d+)$")


def source_and_index(stem: str, fallback_source: str) -> tuple[str, int | None]:
    """('Japan', 123) for 'Japan_000123'; the fallback source and no index for other names."""
    match = _NUMBERED.match(stem)
    return (match["source"], int(match["index"])) if match else (fallback_source, None)


@dataclass(frozen=True)
class SplitItem:
    key: str            # unique identifier of the image
    source: str
    index: int | None
    content_hash: str | None = None


class _Groups:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, name: str) -> str:
        self.parent.setdefault(name, name)
        while self.parent[name] != name:
            self.parent[name] = self.parent[self.parent[name]]
            name = self.parent[name]
        return name

    def union(self, first: str, second: str) -> None:
        self.parent[self.find(second)] = self.find(first)


def assign_groups(items: list[SplitItem], block_size: int) -> dict[str, str]:
    """Map every item key to the name of its leakage group."""
    groups = _Groups()
    initial: dict[str, str] = {}
    first_with_hash: dict[str, str] = {}
    for item in items:
        name = f"{item.source}#{item.index // block_size:06d}" if item.index is not None else f"{item.source}#single#{item.key}"
        initial[item.key] = name
        groups.find(name)
        if item.content_hash:
            if item.content_hash in first_with_hash:
                groups.union(first_with_hash[item.content_hash], name)
            else:
                first_with_hash[item.content_hash] = name
    return {key: groups.find(name) for key, name in initial.items()}


def split_items(items: list[SplitItem], val_fraction: float, test_fraction: float, block_size: int = 50, seed: int = 42,
                test_sources: frozenset[str] = frozenset()) -> tuple[dict[str, str], dict[str, str]]:
    """Return ({item key: split}, {item key: group}). Deterministic for a given seed.

    Groups are kept whole. Each source is split separately so every split sees
    every source, unless the source is named in ``test_sources``; then all of
    it goes to test and the remaining sources are divided between train and
    validation only.
    """
    if not 0 <= val_fraction < 1 or not 0 <= test_fraction < 1 or val_fraction + test_fraction >= 1:
        raise ValueError("val and test fractions must be in [0, 1) and sum to less than 1")
    if block_size < 1:
        raise ValueError("block size must be at least 1")
    group_of = assign_groups(items, block_size)
    members: dict[str, list[SplitItem]] = defaultdict(list)
    for item in items:
        members[group_of[item.key]].append(item)

    if test_sources:
        kept = 1 - test_fraction
        targets = {"train": (1 - val_fraction - test_fraction) / kept, "val": val_fraction / kept, "test": 0.0}
    else:
        targets = {"train": 1 - val_fraction - test_fraction, "val": val_fraction, "test": test_fraction}

    by_source: dict[str, list[str]] = defaultdict(list)
    assignment: dict[str, str] = {}
    for name, group in members.items():
        sources = {item.source for item in group}
        if sources & test_sources:
            # A group that touches a held-out source goes to test in full, so merged duplicates cannot straddle.
            assignment.update({item.key: "test" for item in group})
        else:
            by_source[min(sources)].append(name)

    for source in sorted(by_source):
        names = sorted(by_source[source])
        random.Random(f"{seed}:{source}").shuffle(names)
        counts = dict.fromkeys(SPLITS, 0)
        total = 0
        wanted = [split for split in SPLITS if targets[split] > 0]
        # With enough groups, every wanted split gets one before shares are balanced,
        # so a small dataset cannot end up with an empty validation or test split.
        guaranteed = wanted if len(names) >= len(wanted) else []
        for position, name in enumerate(names):
            size = len(members[name])
            total += size
            if position < len(guaranteed):
                split = guaranteed[position]
            else:
                # Give the group to whichever split is furthest below its target share.
                split = max(SPLITS, key=lambda candidate: (targets[candidate] * total - counts[candidate], -SPLITS.index(candidate)))
            counts[split] += size
            assignment.update({item.key: split for item in members[name]})
    return assignment, group_of
