from pathlib import Path

import pytest

from foodlogger.training import split_dataset


def make_tree(root):
    for split, count in [("train", 5), ("test", 2)]:
        for label in ["pizza", "banana"]:
            folder = root / split / label
            folder.mkdir(parents=True)
            for index in range(count):
                (folder / f"{index}.jpg").touch()


def test_split_is_stratified_repeatable_and_keeps_test_separate(tmp_path):
    make_tree(tmp_path)
    manifest = split_dataset(tmp_path, validation_fraction=0.2, seed=42)
    assert manifest == split_dataset(tmp_path, validation_fraction=0.2, seed=42)
    assert manifest["labels"] == ["banana", "pizza"]
    assert len(manifest["train"]) == 8
    assert len(manifest["validation"]) == 2
    assert len(manifest["test"]) == 4
    assert {label for _, label in manifest["validation"]} == {0, 1}
    all_paths = [path for split in ("train", "validation", "test") for path, _ in manifest[split]]
    assert len(all_paths) == len(set(all_paths))
    root = tmp_path.resolve()
    assert all(Path(path).relative_to(root).parts[0] == "test" for path, _ in manifest["test"])


def test_missing_or_mismatched_test_classes_are_rejected(tmp_path):
    make_tree(tmp_path)
    (tmp_path / "test" / "banana").rename(tmp_path / "test" / "apple")
    with pytest.raises(ValueError, match="same classes"):
        split_dataset(tmp_path)


def test_too_few_training_images_fail_before_tensorflow(tmp_path):
    make_tree(tmp_path)
    for path in sorted((tmp_path / "train" / "pizza").glob("*.jpg"))[1:]:
        path.unlink()
    with pytest.raises(ValueError, match="at least two"):
        split_dataset(tmp_path)


def test_path_overlap_between_train_and_test_is_rejected(tmp_path, make_symlink):
    make_tree(tmp_path)
    test_image = tmp_path / "test" / "pizza" / "0.jpg"
    test_image.unlink()
    make_symlink(test_image, tmp_path / "train" / "pizza" / "0.jpg")
    with pytest.raises(ValueError, match="overlap"):
        split_dataset(tmp_path)


def test_empty_dataset_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        split_dataset(Path(tmp_path))
