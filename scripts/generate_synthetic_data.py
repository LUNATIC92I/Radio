"""Génère les données synthétiques de démonstration (data/synthetic/). Toutes sont marquées SIMULÉES."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lunatic_radio_lab.dsp.audio import AudioClip, save_wav, synthetic_test_clip  # noqa: E402
from lunatic_radio_lab.dsp.demod import channelize, fm_demodulate  # noqa: E402
from lunatic_radio_lab.dsp.synth import Emitter, Scenario, SignalGenerator, preset_scenarios  # noqa: E402
from lunatic_radio_lab.iq_io import write_sigmf  # noqa: E402

OUT = ROOT / "data" / "synthetic"
FS, FC = 250_000.0, 446.1e6


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "scenarios").mkdir(exist_ok=True)
    for key, sc in preset_scenarios().items():
        (OUT / "scenarios" / f"{key}.json").write_text(json.dumps(sc.to_dict(), indent=2, ensure_ascii=False),
                                                       encoding="utf-8")
    captures = {
        "fm_test_1khz_ctcss88": [Emitter("fm_tone", FC + 25_000, -35, ctcss_hz=88.5, label="FM test")],
        "fm_voix_synthetique": [Emitter("fm_voice", FC - 40_000, -38, ctcss_hz=123.0, label="FM voix")],
        "fsk4_tdma_type_dmr": [Emitter("fsk4_tdma", FC + 6_875, -38, deviation_hz=1944, label="4FSK TDMA")],
    }
    for name, em in captures.items():
        g = SignalGenerator(Scenario(name, emitters=em, noise_dbfs=-60, seed=11), FS)
        iq = g.generate(int(0.5 * FS), FC)
        write_sigmf(OUT / f"{name}", iq, FS, FC, simulated=True,
                    description=f"DONNÉES SIMULÉES — {name} (aucune trame de protocole réel)",
                    hw="LUNATIC SIM-1 (simulation)",
                    annotations=[{"core:sample_start": 0, "core:sample_count": len(iq),
                                  "core:freq_lower_edge": em[0].freq_hz - 6250, "core:freq_upper_edge": em[0].freq_hz + 6250,
                                  "core:label": em[0].label, "lrl:simulated": True}])
        if name.startswith("fm_"):
            x, fs2 = channelize(iq, FS, em[0].freq_hz - FC, 12_500, min_rate=32_000)
            save_wav(AudioClip(fm_demodulate(x, fs2, 16_000, 2_500), 16_000, simulated=True),
                     OUT / f"{name}_demodule.wav")
    save_wav(synthetic_test_clip(3.0), OUT / "audio_test_tonalite_1khz_bruit.wav")
    (OUT / "LISEZMOI.txt").write_text(
        "Toutes les données de ce dossier sont SYNTHÉTIQUES (mode laboratoire de LUNATIC RADIO LAB).\n"
        "Elles ne proviennent d'aucune réception radio réelle. Les signaux 4FSK ne contiennent aucune trame\n"
        "de protocole réel : seules leurs propriétés physiques imitent les familles documentées.\n"
        "Les captures IQ sont au format SigMF (cf32_le) avec la métadonnée lrl:simulated = true.\n",
        encoding="utf-8")
    print(f"Données synthétiques écrites dans {OUT}")


if __name__ == "__main__":
    main()
