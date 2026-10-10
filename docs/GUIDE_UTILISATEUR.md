# Guide utilisateur

## Premier lancement

1. `scripts/run.sh` (Windows : `scripts\run.bat`).
2. **Sécurité & conformité** → « Définir / changer le code » : choisissez un code administrateur (≥ 6 caractères).
   Il protège les canaux, l'étalonnage, la purge de l'historique, la juridiction et les récepteurs réseau.
   Le déverrouillage dure 10 minutes ; 5 échecs bloquent l'accès 60 s. Tout est journalisé.
3. Renseignez la **juridiction** et, dans « Configuration récepteur », le **nom de l'opérateur** (rapports).
4. **Canaux autorisés** : saisissez les canaux que vous êtes autorisé à surveiller (ou importez le plan PMR446
   public). Chaque canal porte une référence d'autorisation ; l'option « Enregistrement / démodulation audio
   autorisés » conditionne la démodulation et la capture IQ sur ce canal.

La barre d'état indique en permanence **DONNÉES SIMULÉES** (violet) ou **MESURE RÉELLE** (bleu), l'état de
l'acquisition, la **saturation** éventuelle et l'état de l'accès administrateur.

## Écrans

**Tableau de bord** — récepteur, nature des données, fréquence, plancher de bruit, événements de la dernière heure,
saturation ; spectre en direct ; émissions présentes ; derniers événements ; bouton Autotest.

**Équipements** — liste des récepteurs (SoapySDR, GNU Radio, USB sans pilote, simulation) et capacités déclarées.
« Utiliser cet équipement » ou « Assistant de configuration ».

**Analyseur de spectre** — réglez fréquence, échantillonnage (= largeur observée), gain/AGC, taille FFT (résolution),
moyennage vidéo, max-hold. Les zones bleues sont les canaux autorisés, les zones vertes les émissions détectées.
Lignes : plancher (jaune), seuil de détection (rouge). Panneau « Mesures » : marqueur, RBW, moyennage, saturation,
dynamique ADC et rappel des limites de précision.

**Waterfall** — historique temporel ; niveaux automatiques (plancher −5 dB à +55 dB) ou manuels ; clic = fréquence.

**Détection d'activité** — paramètres :
- *seuil d'ouverture* : dépassement du plancher pour ouvrir un événement ;
- *hystérésis* : maintien tant que le niveau dépasse seuil − hystérésis ;
- *persistance* : trames consécutives nécessaires (anti-impulsions) ;
- *durée minimale*, *temps de maintien* (pontage des coupures courtes) ;
- *tolérance de fréquence*, *largeurs min/max*, *exclusion DC*, *uniquement canaux autorisés*.
Chaque événement enregistre fréquence configurée et mesurée, début/fin, durée, puissance crête/moyenne (puissance
de canal), SNR, largeur estimée, récepteur, paramètres de détection et caractérisation automatique.

**Identification signaux** — choisissez une émission détectée (ou un fichier SigMF) puis « Analyser ». Le verdict
est « Compatible avec … (confiance N %) » ou « Non identifié ». Le tableau classe toutes les hypothèses ; la
sélection d'une hypothèse liste les éléments favorables (✔), contraires (✘), non mesurés (?) et les notes.
Les profils numériques sont plafonnés (DMR 60 %, P25 50 %, 4FSK 6,25 kHz 50 %) ; si le motif de
synchronisation public de la norme est trouvé, le plafond passe à 90 %. Aucun contenu n'est décodé.
La mention « superposition suspectée » signale une collision probable (deux émissions sur le même canal).

**Analyse audio** — ouvrir un fichier (copie sécurisée + empreinte SHA-256), clip de test, ou démoduler une
émission FM (direct : canal autorisé à l'enregistrement + attestation ; fichier SigMF réel : attestation).
Forme d'onde (la zone cyan sert au découpage), spectrogramme, niveaux, traitements avec annulation, lecture, export.

*Écoute en direct* : choisissez la fréquence (ou « Prendre l'émission la plus forte »), le squelch (dB au-dessus
du bruit du canal) puis « Écouter ». Sur des données réelles, la fréquence doit être couverte par un canal autorisé
portant une référence d'autorisation, et l'opérateur doit confirmer son autorisation ; l'option « Enregistrer en
WAV » exige en plus « enregistrement autorisé » sur ce canal. Les fichiers sont écrits dans `captures/`. L'écoute
s'arrête automatiquement si un changement de fréquence fait sortir le canal de la bande observée.

**Historique** — filtres (dates, fréquences, puissance, durée, canal, nature), export CSV, purge (administrateur).

**Canaux autorisés** — « Vérifier » affiche erreurs (⛔) et avertissements (⚠) : chevauchement, canalisation du
profil, capacités du récepteur, vérification réglementaire, référence d'autorisation manquante.

**Configuration récepteur** — paramètres RF complets (filtre, ppm, antenne), étalonnage dBm (protégé), capture IQ
SigMF (bande entièrement couverte par des canaux autorisés à l'enregistrement, sauf simulation), rejeu IQ.

**Mode laboratoire** — scénarios prédéfinis (porteuse, FM de test, intermittences, bruit élevé, canaux occupés,
collision, variations de puissance) ou personnalisés ; « Appliquer au récepteur simulé » ; import/export JSON.

**Console technique** — journal en direct et commandes `help`, `status`, `devices`, `start`, `stop`, `tune`,
`rate`, `gain`, `detections`, `events`, `selftest`, `audit`. Aucune exécution de code arbitraire.

**Rapports** — période, nature des données, spectre max-hold ; génère PDF + CSV (événements) + CSV de
métadonnées dans `~/.lunatic_radio_lab/reports/`. Liste des résultats de tests.

**Sécurité & conformité** — accès administrateur, juridiction, rappels réglementaires, journal d'audit.

## Interpréter les mesures

- **dBFS** : relatif à la pleine échelle de l'ADC. Comparez des niveaux entre eux, pas avec des dBm (sauf
  étalonnage).
- **Puissance par case** (spectre) ≠ **puissance de canal** (événements) : la seconde intègre toutes les cases de
  l'émission.
- **Largeur « n/m »** : émission plus étroite qu'environ 2 RBW ; augmentez la taille FFT.
- **SNR des rafales** : pour les émissions TDMA, le SNR est corrigé du rapport cyclique.

## Données et fichiers

`~/.lunatic_radio_lab/` (ou `$LRL_HOME`) : base `lunatic_radio_lab.sqlite3`, `imports/` (copies en lecture seule),
`captures/`, `reports/`, `logs/` (journal tournant).
