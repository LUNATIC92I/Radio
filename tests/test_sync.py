import numpy as np

from lunatic_radio_lab.dsp.sync import PATTERNS, find_sync, pattern_symbols


def test_pattern_mapping():
    # 0x7 = 01 11 -> +3 -3
    assert list(pattern_symbols("7")[:0]) == []
    assert list(pattern_symbols("75")) == [3, -3, 3, 3]
    for pat, _ in PATTERNS.values():
        assert len(pat) == 24 and set(np.unique(pat)) <= {-3, -1, 1, 3}


def test_dmr_voice_data_are_negations():
    assert np.array_equal(PATTERNS["DMR MS données"][0], -PATTERNS["DMR MS voix"][0])
    assert np.array_equal(PATTERNS["DMR BS données"][0], -PATTERNS["DMR BS voix"][0])


def test_find_sync_with_errors_and_random_rejection():
    rng = np.random.default_rng(1)
    sym = rng.choice([-3, -1, 1, 3], size=5000).astype(np.int8)
    assert find_sync(sym).matches == {}  # pas de faux positif sur 5000 symboles aléatoires
    pat = PATTERNS["P25 Phase 1 FS"][0].copy()
    pat[3] = -pat[3]
    pat[10] = -pat[10]  # 2 erreurs tolérées
    sym[1000:1024] = pat
    r = find_sync(sym)
    assert r.matches == {"P25 Phase 1 FS": 1} and r.profile_hits == {"p25_p1": 1}
