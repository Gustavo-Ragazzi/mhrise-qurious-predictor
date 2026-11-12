"""Generator checks that run anywhere (values sampled from the game's via.Random.genU32/genF32)."""

from qurious_predictor.rng import XorShift128


def test_gen_u32_matches_game():
    rng = XorShift128((0x8C947F67, 0xDE6FE7D0, 0x6EC4E2CC, 0x9F5B65EC))
    assert [rng.next_u32() for _ in range(6)] == [659480967, 135362832, 373929392, 960366256, 1808511206,
                                                   3558563129]
    assert rng.state() == (0x1649B5B0, 0x393E06B0, 0x6BCBB0E6, 0xD41B5D39)


def test_gen_f32_matches_game():
    rng = XorShift128((0x2DF6ACA3, 0x4DE0181C, 0x438B5C89, 0xD057AA53))
    assert abs(rng.next_f32() - 0.67301863431931) < 1e-6


def test_state_from_save_bytes():
    raw = bytes.fromhex("0807d2cf04471088b8719b71548d6818")  # GUID as stored in the save
    assert XorShift128.from_bytes(raw).state() == (0xCFD20708, 0x88104704, 0x719B71B8, 0x18688D54)
