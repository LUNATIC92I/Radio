# Bilan des fonctionnalités et limitations

État de la version 1.0.0. « Validé » signifie couvert par les tests automatisés (79 tests) ; les tests sur
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
- **Identification** : hypothèses physiques uniquement ; les profils numériques sont plafonnés (DMR 60 %,
  P25 50 %, 6,25 kHz 50 %) faute de vérification des motifs de synchronisation. Un relais DMR (émission
  continue) n'est pas distinguable d'un P25 Phase 1 : le résultat est alors la famille « 4FSK 4800 Bd — non
  déterminé ». P25 Phase 2, TETRA, NXDN 12,5 kHz et dPMR vs NXDN 6,25 kHz ne sont pas distingués.
- **Signaux faibles** : sous ≈ 6 dB de SNR les mesures de modulation sont signalées peu fiables et la confiance
  est réduite ; la détection nécessite par défaut 10 dB au-dessus du plancher.
- **Collisions** : deux émissions superposées sur le même canal sont vues comme un seul événement.
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
