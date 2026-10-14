import pandas as pd
import pandera.pandas as pa
import pytest

from amr_prediction.data import EXPORT, ROWS, validate


@pytest.fixture()
def sample():
    # 21 настоящая последовательность, по 3 на класс; датасет из DVC для тестов не нужен
    return pd.read_csv("examples/sample_test_sequences.csv")


def test_good_rows_pass(sample):
    ROWS.validate(sample, lazy=True)


def test_dna_instead_of_protein_caught(sample):
    # буквы A, C, G, T допустимы и в белке, ловит только состав
    sample.loc[0, "sequence"] = "ATGGCTAAACGTTCAGGCATTACCGATGCTGCAAAGCTGTTCGGTACC"
    with pytest.raises(pa.errors.SchemaErrors) as e:
        ROWS.validate(sample, lazy=True)
    assert set(e.value.failure_cases["check"]) == {"composition_l1"}


def test_same_sequence_two_classes_caught(sample):
    sample.loc[1, "sequence"] = sample.loc[0, "sequence"]
    with pytest.raises(pa.errors.SchemaErrors) as e:
        ROWS.validate(sample, lazy=True)
    assert "field_uniqueness" in set(e.value.failure_cases["check"])


def test_small_export_rejected(sample):
    with pytest.raises(pa.errors.SchemaErrors) as e:
        EXPORT.validate(sample, lazy=True)
    assert "rows_min_12000" in set(e.value.failure_cases["check"])
    assert len(validate(sample)) > 0
