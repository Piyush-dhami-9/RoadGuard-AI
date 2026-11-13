from collections import Counter, defaultdict
import pytest
from model.training.splits import SplitItem, assign_groups, source_and_index, split_items


def items(source: str, count: int) -> list[SplitItem]:
    return [SplitItem(f"{source}_{index:06d}", source, index) for index in range(count)]


@pytest.mark.parametrize("stem, expected", [
    ("Japan_000123", ("Japan", 123)), ("United_States_004805", ("United_States", 4805)), ("China_MotorBike_000001", ("China_MotorBike", 1)),
    ("IMG4512", ("folder", None)), ("photo_final", ("folder", None)),
])
def test_source_and_index_from_rdd_file_names(stem, expected):
    assert source_and_index(stem, "folder") == expected


def test_consecutive_images_share_a_group_and_groups_never_straddle_splits():
    data = items("Japan", 1000) + items("India", 600)
    assignment, group_of = split_items(data, 0.1, 0.1, block_size=50, seed=1)
    assert group_of["Japan_000000"] == group_of["Japan_000049"] != group_of["Japan_000050"]
    assert group_of["Japan_000000"] != group_of["India_000000"]
    splits_of_group = defaultdict(set)
    for key, split in assignment.items():
        splits_of_group[group_of[key]].add(split)
    assert all(len(splits) == 1 for splits in splits_of_group.values())


def test_fractions_are_respected_per_source():
    data = items("Japan", 2000) + items("India", 1000)
    assignment, _ = split_items(data, 0.1, 0.1, block_size=50, seed=3)
    for source, total in (("Japan", 2000), ("India", 1000)):
        counts = Counter(split for key, split in assignment.items() if key.startswith(source))
        assert counts["train"] == total * 0.8 and counts["val"] == total * 0.1 and counts["test"] == total * 0.1


def test_split_is_deterministic_and_changes_with_the_seed():
    data = items("Japan", 1000)
    assert split_items(data, 0.1, 0.1, seed=7)[0] == split_items(list(reversed(data)), 0.1, 0.1, seed=7)[0]
    assert split_items(data, 0.1, 0.1, seed=7)[0] != split_items(data, 0.1, 0.1, seed=8)[0]


def test_held_out_source_goes_entirely_to_test_and_others_only_to_train_and_val():
    data = items("Japan", 1000) + items("Norway", 300)
    assignment, _ = split_items(data, 0.1, 0.1, block_size=50, seed=1, test_sources=frozenset({"Norway"}))
    assert {split for key, split in assignment.items() if key.startswith("Norway")} == {"test"}
    japan = Counter(split for key, split in assignment.items() if key.startswith("Japan"))
    assert japan["test"] == 0 and japan["val"] > 0 and japan["train"] > japan["val"] * 5


def test_byte_identical_images_are_grouped_even_across_blocks_and_sources():
    data = [SplitItem("a", "Japan", 10, "samehash"), SplitItem("b", "Japan", 990, "samehash"), SplitItem("c", "India", 5, "samehash"), SplitItem("d", "India", 500, "other")]
    groups = assign_groups(data, 50)
    assert groups["a"] == groups["b"] == groups["c"] != groups["d"]
    for seed in range(20):
        assignment, _ = split_items(data + items("Czech", 500), 0.2, 0.2, seed=seed)
        assert assignment["a"] == assignment["b"] == assignment["c"]


def test_images_without_a_number_are_split_individually():
    data = [SplitItem(f"photo{index}", "misc", None) for index in range(100)]
    assignment, group_of = split_items(data, 0.2, 0.2, seed=1)
    assert len(set(group_of.values())) == 100
    assert Counter(assignment.values()) == {"train": 60, "val": 20, "test": 20}


@pytest.mark.parametrize("val, test", [(0.5, 0.5), (-0.1, 0.1), (0.1, 1.0)])
def test_bad_fractions_are_refused(val, test):
    with pytest.raises(ValueError):
        split_items(items("Japan", 10), val, test)
