# Bilan des fonctionnalités et limitations

État de la version 1.0.0. « Validé » signifie couvert par les tests automatisés (86 tests) ; les tests sur
matériel réel n'ont **pas** pu être réalisés dans l'environnement de développement (aucun récepteur connecté).

## Disponible et validé

| Fonction | Validation |
|---|---|
| Mode simulation complet (récepteur 12 bits simulé, saturation, quantification, ppm) | tests + autotest |
| Spectre Welch : exactitude puissance ±0,2 dB, fréquence ±1 case sur signaux synthétiques | tests |
| Plancher de bruit, RBW/ENBW, saturation | tests |
| Détection d'émissions, largeur de bande 99 %, filtres | tests |
| Moteur d'activité (hystérésis, persistance, durée min, maintien, canaux) | tests |
| Caractérisation : CW, FM 1 kHz, FM vocale, 4FSK TDMA 4800 Bd, 4FSK continu 4800 Bd, 4FSK 2400 Bd ; rejet du bruit et des signaux faibles | tests |
| Motifs de synchronisation publics DMR (BS/MS voix/données) et P25 Phase 1 : détection jusqu'à 2 symboles erronés, aucun faux positif sur 5000 symboles aléatoires | tests |
| Indicateur de superposition d'émissions (collision partielle) | tests |
| Démodulation FM analogique | tests |
| Audio : niveaux, passe-bande, réduction de bruit, normalisation, découpage, WAV, FFmpeg | tests |
| Stockage SQLite, audit, contrôle d'accès PBKDF2, verrouillage | tests |
| Import sécurisé (liens, extension, taille, signature, SHA-256) | tests |
| Canaux autorisés : validation, droits, import/export, PMR446 | tests |
| Rapports PDF/CSV, séparation réel/simulé | tests + exemple fourni |
| SigMF lecture/écriture, rejeu IQ, formats bruts | tests |
| Pilote SoapySDR (logique d'énumération, configuration, lecture, réception seule) | tests avec module SoapySDR simulé |
| Détection USB passive | tests (sysfs simulé) |
| Interface graphique 14 écrans | tests pytest-qt (offscreen) + captures |
| CLI | tests |

## Disponible, non validé sur matériel

- **SoapySDR sur récepteur réel** : la logique est testée contre une maquette de l'API ; le comportement réel
  (débits, timeouts, gains par étage) dépend du module matériel.
- **GNU Radio / gr-osmosdr** : implémenté, non testé (bibliothèques absentes de l'environnement).
- **Lecture audio** : dépend de QtMultimedia et du système audio ; désactivée proprement si indisponible.

## Limitations techniques

- **Puissance relative (dBFS)** ; dBm seulement après étalonnage manuel, valable pour un gain/fréquence/câblage.
- **Précision en fréquence** limitée par l'oscillateur du récepteur (corriger en ppm) et la résolution FFT.
- **Dynamique** limitée par l'ADC (≈ 50 dB pour 8 bits, ≈ 74 dB pour 12 bits, hors gain de traitement).
- **Identification** : hypothèses physiques. Sans motif de synchronisation, les profils numériques sont plafonnés
  (DMR 60 %, P25 50 %, 6,25 kHz 50 %) et un 4FSK 4800 Bd continu reste « DMR ou P25 — non déterminé ». Lorsque
  le motif public de la norme est trouvé, le plafond passe à 90 % (jamais 100 %). La synchronisation n'est
  recherchée qu'en 4800 Bd (pas de motif dPMR/NXDN). Les motifs DMR « données » étant l'opposé des motifs
  « voix », une inversion de spectre fait lire l'un pour l'autre (la famille reste correcte). Les signaux 4FSK
  synthétiques ne contiennent que le motif, entouré de symboles aléatoires. P25 Phase 2, TETRA, NXDN 12,5 kHz et dPMR vs NXDN 6,25 kHz ne sont pas distingués.
- **Signaux faibles** : sous ≈ 6 dB de SNR les mesures de modulation sont signalées peu fiables et la confiance
  est réduite ; la détection nécessite par défaut 10 dB au-dessus du plancher.
- **Collisions** : deux émissions superposées restent un seul événement, signalé « superposition suspectée »
  lorsque l'enveloppe est perturbée sur une partie seulement de l'émission (SNR ≥ 15 dB). Une superposition
  couvrant toute l'émission n'est pas distinguée d'une modulation à enveloppe variable.
- **Signaux FM vocaux** : la largeur mesurée par trame dépend du contenu instantané (médiane sur l'événement).
- **Débit** : traitement en Python/NumPy, adapté à ≈ 3 MS/s sur un poste récent ; au-delà, augmenter la taille de
  bloc ou réduire l'échantillonnage.
- **Écoute temps réel continue** : non proposée ; la démodulation porte sur le tampon des dernières secondes.
- **Classification automatique des événements** : effectuée seulement si l'événement est encore dans le tampon
  circulaire (4 s par défaut).
- **Plage de fréquences** : celle du matériel ; le logiciel ne prétend pas recevoir au-delà.

## Exclusions volontaires

Émission radio, brouillage, usurpation de station, décodage de voix numérique (AMBE, IMBE…), déchiffrement,
contournement d'authentification, listes de fréquences sensibles, envoi de données sur le réseau.
