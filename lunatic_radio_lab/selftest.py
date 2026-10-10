"""Autotests de la chaîne de mesure et test de réception d'un récepteur réel."""

from __future__ import annotations

import time

import numpy as np

from .dsp.classifier import classify_iq
from .dsp.detection import detect_emissions
from .dsp.spectrum import SpectrumAnalyzer, saturation_ratio
from .dsp.synth import Emitter, Scenario
from .drivers.base import Receiver
from .drivers.simulated import SimulatedReceiver
from .models import ReceiverConfig, TestResult


def run_selftests(fft_size: int = 4096) -> list[TestResult]:
    """Vérifie la chaîne DSP sur des signaux synthétiques de caractéristiques connues."""
    results: list[TestResult] = []
    fc, fs = 446.1e6, 250_000.0
    f_true, p_true = fc + 31_250.0, -40.0
    scen = Scenario("autotest", noise_dbfs=-70.0, emitters=[Emitter("carrier", f_true, p_true)], seed=1)
    rx = SimulatedReceiver(scen, realtime=False)
    rx.open()
    rx.configure(ReceiverConfig(fc, fs, 30.0))
    an = SpectrumAnalyzer(fft_size)
    iq = rx.read(fft_size * 16)
    fr = an.process(iq, fc, fs, rx.info.device_id, True)
    dets = detect_emissions(fr)
    bin_hz = fs / fft_size
    if dets:
        d = max(dets, key=lambda x: x.peak_dbfs)
        f_err, p_err = d.center_freq_hz - f_true, d.channel_power_dbfs - p_true
    else:
        f_err = p_err = float("nan")
    results.append(TestResult("Exactitude fréquence (porteuse simulée)", bool(dets) and abs(f_err) <= 2 * bin_hz,
                              {"erreur_hz": f_err, "tolerance_hz": 2 * bin_hz, "rbw_hz": fr.rbw_hz}, True, rx.info.device_id))
    results.append(TestResult("Exactitude puissance de canal (porteuse simulée)", bool(dets) and abs(p_err) <= 1.0,
                              {"erreur_db": p_err, "tolerance_db": 1.0}, True, rx.info.device_id))
    results.append(TestResult("Absence de saturation au gain nominal", not fr.saturated,
                              {"taux_saturation": fr.saturation_ratio}, True, rx.info.device_id))
    # saturation volontaire : signal fort + gain maximal
    rx.set_scenario(Scenario("sat", noise_dbfs=-70.0, emitters=[Emitter("carrier", f_true, -5.0)]))
    rx.configure(ReceiverConfig(fc, fs, 60.0))
    sat = saturation_ratio(rx.read(fft_size * 4))
    results.append(TestResult("Détection de saturation (signal fort, gain max)", sat > 1e-3,
                              {"taux_saturation": sat}, True, rx.info.device_id))
    # caractérisation : porteuse et FM de test
    for kind, expect in (("carrier", "test_cw"), ("fm_tone", "test_fm_1k")):
        rx.set_scenario(Scenario("cls", noise_dbfs=-65.0, emitters=[Emitter(kind, f_true, -35.0)]))
        rx.configure(ReceiverConfig(fc, fs, 30.0))
        c = classify_iq(rx.read(int(fs)), fs, f_true - fc, fc, simulated=True)
        ok = c.best is not None and c.best.profile_id == expect and c.best.confidence >= 0.5
        results.append(TestResult(f"Caractérisation « {kind} »", ok,
                                  {"attendu": expect, "obtenu": c.best.profile_id if c.best else None,
                                   "confiance": c.best.confidence if c.best else None}, True, rx.info.device_id))
    # rejet du bruit seul
    rx.set_scenario(Scenario("bruit", noise_dbfs=-60.0))
    fr = an.process(rx.read(fft_size * 16), fc, fs, rx.info.device_id, True)
    nd = len(detect_emissions(fr))
    results.append(TestResult("Aucune fausse détection sur bruit seul", nd == 0, {"detections": nd}, True,
                              rx.info.device_id))
    rx.close()
    return results


def reception_test(receiver: Receiver, cfg: ReceiverConfig, seconds: float = 1.0, fft_size: int = 4096) -> TestResult:
    """Test de réception d'un récepteur (assistant) : débit effectif, bruit, saturation, DC."""
    details: dict = {"config": cfg.to_dict(), "recepteur": receiver.info.label}
    passed = True
    opened_here = False
    try:
        if not receiver.is_open:
            receiver.open()
            opened_here = True
        applied = receiver.configure(cfg)
        details["config_appliquee"] = applied.to_dict()
        n_total = int(seconds * applied.sample_rate_hz)
        blk = 65_536
        chunks = []
        t0 = time.monotonic()
        got = 0
        while got < n_total:
            x = receiver.read(min(blk, n_total - got))
            chunks.append(x)
            got += len(x)
        dt = time.monotonic() - t0
        iq = np.concatenate(chunks)
        fr = SpectrumAnalyzer(fft_size).process(iq, applied.center_freq_hz, applied.sample_rate_hz,
                                                receiver.info.device_id, receiver.simulated, applied.gain_db)
        details.update({
            "echantillons": int(len(iq)),
            "duree_lecture_s": dt,
            "debit_effectif_Sps": len(iq) / dt if dt > 0 else None,
            "plancher_bruit_dbfs_par_case": fr.noise_floor_dbfs,
            "rbw_hz": fr.rbw_hz,
            "taux_saturation": fr.saturation_ratio,
            "composante_continue": float(np.abs(np.mean(iq))),
            "niveau_rms_dbfs": float(10 * np.log10(np.mean(np.abs(iq) ** 2) + 1e-20)),
            "emissions_detectees": len(detect_emissions(fr)),
        })
        if not np.isfinite(iq).all():
            passed = False
            details["probleme"] = "Échantillons non finis"
        if fr.saturated:
            passed = False
            details["probleme"] = "Saturation : réduisez le gain"
        if not receiver.simulated and dt > 0 and len(iq) / dt < 0.5 * applied.sample_rate_hz:
            details["avertissement"] = "Débit effectif inférieur à 50 % : pertes USB probables"
    except Exception as exc:  # noqa: BLE001
        passed = False
        details["erreur"] = str(exc)
    finally:
        if opened_here:
            try:
                receiver.close()
            except Exception:  # noqa: BLE001
                pass
    return TestResult("Test de réception", passed, details, receiver.simulated, receiver.info.device_id)
