# LUNATIC RADIO LAB

Logiciel professionnel de **réception autorisée**, d'**analyse technique** et de **surveillance de l'état** des
communications radio (talkie-walkies analogiques et numériques), destiné aux techniciens radio, laboratoires de
test, équipes de maintenance, opérateurs autorisés et professionnels de la cybersécurité des télécommunications.

> **Réception seule.** Le logiciel ne contient aucune fonction d'émission, de brouillage, d'usurpation de station
> ou de déchiffrement. Les protocoles numériques sont uniquement *caractérisés* par leurs propriétés physiques.
> Il fonctionne localement (aucune donnée envoyée sur le réseau).

## Démarrage rapide

```bash
scripts/install.sh          # Windows : scripts\install.bat
scripts/run.sh              # interface graphique (Windows : scripts\run.bat)
```

Sans matériel, l'application démarre en **mode simulation** (bandeau violet « DONNÉES SIMULÉES »). Dans
« Mode laboratoire », choisissez un scénario puis « Démarrer » depuis le tableau de bord.

Ligne de commande :

```bash
python -m lunatic_radio_lab devices                       # récepteurs détectés
python -m lunatic_radio_lab selftest                      # autotests de la chaîne de mesure
python -m lunatic_radio_lab simulate --scenario canaux_occupes --seconds 20 --report rapport.pdf
python -m lunatic_radio_lab report sortie.pdf --hours 24 --real-only
```

## Fonctionnalités

| Domaine | Contenu |
|---|---|
| Équipements | Détection SoapySDR, GNU Radio (gr-osmosdr), USB passive (VID:PID) ; fabricant, modèle, capacités, plage, état ; assistant (sélection → compatibilité → test de réception) ; simulation sans matériel |
| Spectre | Welch moyenné, dBFS, RBW/ENBW affichée, plancher de bruit, max-hold, marqueur, détection d'émissions, largeur de bande occupée 99 %, indicateur de saturation ADC, dynamique ADC |
| Waterfall | Historique configurable, niveaux auto/manuels, lecture de fréquence |
| Activité | Seuil d'ouverture + hystérésis, persistance, durée minimale, temps de maintien, filtres de largeur, exclusion DC, filtre de canaux autorisés ; événements horodatés en base |
| Identification | Largeur de bande, SNR, enveloppe, rafales/TDMA, dérive et stabilité de fréquence, excursion, débit symbole, niveaux 4FSK, CTCSS, tonalité d'essai, **motifs de synchronisation publics DMR/P25** (sans décodage), **superposition d'émissions** ; hypothèses avec confiance plafonnée et justification |
| Audio | WAV (+ MP3/FLAC/OGG via FFmpeg), forme d'onde, spectrogramme, niveaux, passe-bande, réduction de bruit, normalisation, découpage, export WAV, démodulation FM et **écoute en direct avec squelch** (canaux autorisés uniquement, enregistrement WAV optionnel) |
| Laboratoire | Porteuse, FM de test, voix synthétique, 4FSK TDMA/continu/6,25 kHz, intermittences, bruit, évanouissements, dérive, canaux occupés, collisions ; scénarios JSON |
| Canaux | Gestion des canaux autorisés (admin), validation, avertissements réglementaires et capacités, import plan PMR446 public, import/export JSON/CSV |
| Rapports | PDF (graphiques) + CSV : équipements, paramètres, plages, événements, puissances, tests, erreurs, limites ; réel et simulé séparés |
| Sécurité | Code administrateur PBKDF2, verrouillage après échecs, journal d'audit, import sécurisé, fonctionnement local |

## Architecture

```
lunatic_radio_lab/
  dsp/          traitement du signal : spectre, détection, activité, démodulation FM,
                caractéristiques, classifieur, audio, générateur synthétique
  drivers/      récepteurs : simulation, SoapySDR, GNU Radio, rejeu IQ, scan USB, registre
  protocols/    profils documentés extensibles (FM, PMR446, DMR, P25, 4FSK 6,25 kHz, test)
  storage/      SQLite : paramètres, canaux, sessions, événements, tests, erreurs, audit
  security/     contrôle d'accès, import sécurisé de fichiers
  reports/      collecte, PDF (ReportLab), CSV
  engine.py     moteur d'acquisition (indépendant de l'interface)
  channels.py   canaux autorisés et validation
  gui/          interface PySide6 + PyQtGraph (14 écrans)
tests/          93 tests pytest (dont interface graphique en mode offscreen)
data/synthetic/ captures SigMF, audio et scénarios synthétiques
docs/           guides, conformité légale, bilan, exemple de rapport
```

## Documentation

- [Guide de configuration SDR](docs/GUIDE_SDR.md)
- [Guide utilisateur](docs/GUIDE_UTILISATEUR.md)
- [Conformité légale](docs/CONFORMITE_LEGALE.md)
- [Bilan des fonctionnalités et limitations](docs/BILAN_FONCTIONNALITES.md)
- [Exemple de rapport PDF](docs/examples/exemple_rapport.pdf) et [CSV](docs/examples/exemple_rapport.csv)

## Dépendances

Python ≥ 3.10 (3.12 recommandé) — NumPy, SciPy, PySide6, PyQtGraph, ReportLab (voir `requirements.txt`).
Optionnels : SoapySDR et ses modules, GNU Radio + gr-osmosdr, FFmpeg, pyusb.

## Tests

```bash
python -m pytest            # QT_QPA_PLATFORM=offscreen est positionné automatiquement
```

Données de démonstration : `python scripts/generate_synthetic_data.py` ;
exemple de rapport : `python scripts/generate_example_report.py`.

Les données utilisateur sont stockées dans `~/.lunatic_radio_lab/` (modifiable via `LRL_HOME`).
