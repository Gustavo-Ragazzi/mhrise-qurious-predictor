import pytest

from mhrise_exporter.save import Class, Scalar, hash_utf8
from qurious_predictor.savedata import armor_for_hunter, hunter_sex


def field(name, value):
    return (hash_utf8(name), 0, value)


@pytest.mark.parametrize("sex", [0, 1])
def test_reads_own_card_only(sex):
    own = Class(0, [field("Sex", Scalar(1, sex.to_bytes(4, "little")))])
    other = Class(0, [field("Sex", Scalar(1, (1 - sex).to_bytes(4, "little")))])
    manager = Class(0, [field("OtherData", [other]), field("MyData", own)])

    class Save:
        def walk_classes(self, name):
            assert name == "snow.GuildCardManager.GuildCardSaveData"
            return iter([manager])

    assert hunter_sex(Save()) == sex


def test_filters_both_catalogs_and_can_switch_hunters():
    armor = {"male": {"sex": 0}, "female": {"sex": 1}, "shared": {"sex": 2}}
    data = {"armors": armor, "all_armors": armor}
    for key in data:
        assert set(armor_for_hunter(data, 0)[key]) == {"male", "shared"}
        assert set(armor_for_hunter(data, 1)[key]) == {"female", "shared"}
        assert armor_for_hunter(data, None)[key] == armor
        assert len(data[key]) == 3
