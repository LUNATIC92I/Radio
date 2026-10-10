import re
from pathlib import Path

from lunatic_radio_lab.cli import main

PKG = Path(__file__).resolve().parents[1] / "lunatic_radio_lab"


def test_cli_commands(lrl_home, capsys):
    assert main(["devices"]) == 0
    assert "simulé" in capsys.readouterr().out
    assert main(["selftest"]) == 0
    out = lrl_home / "r.pdf"
    assert main(["simulate", "--scenario", "fm_test", "--seconds", "3", "--report", str(out)]) == 0
    assert out.exists() and out.with_suffix(".csv").exists()
    assert main(["report", str(lrl_home / "r2.pdf")]) == 0


def test_no_transmit_code_paths():
    """Garde-fou : aucun flux d'émission, aucune fonction d'émission dans le code."""
    forbidden = [r"setupStream\([^)]*SOAPY_SDR_TX", r"writeStream\(", r"osmosdr\.sink", r"\.transmit\(",
                 r"def\s+(transmit|jam|spoof|decrypt)\w*"]
    for f in PKG.rglob("*.py"):
        src = f.read_text(encoding="utf-8")
        for pat in forbidden:
            assert not re.search(pat, src), f"{f}: motif interdit {pat}"


def test_no_network_calls():
    for f in PKG.rglob("*.py"):
        src = f.read_text(encoding="utf-8")
        for mod in ("import requests", "import urllib.request", "import socket", "http.client"):
            assert mod not in src, f"{f}: {mod}"


def test_shipped_synthetic_captures_are_marked_and_classified():
    import pytest
    from lunatic_radio_lab.dsp.classifier import classify_iq
    from lunatic_radio_lab.iq_io import read_sigmf
    data = PKG.parent / "data" / "synthetic"
    expected = {"fm_test_1khz_ctcss88": "test_fm_1k", "fm_voix_synthetique": "fm_nb", "fsk4_tdma_type_dmr": "dmr"}
    offsets = {"fm_test_1khz_ctcss88": 25_000, "fm_voix_synthetique": -40_000, "fsk4_tdma_type_dmr": 6_875}
    for name, pid in expected.items():
        p = data / f"{name}.sigmf-meta"
        if not p.exists():
            pytest.skip("données synthétiques non générées (scripts/generate_synthetic_data.py)")
        cap = read_sigmf(p)
        assert cap.simulated
        c = classify_iq(cap.read(), cap.sample_rate, offsets[name], cap.center_freq, simulated=cap.simulated)
        assert c.best.profile_id == pid, (name, c.verdict)
