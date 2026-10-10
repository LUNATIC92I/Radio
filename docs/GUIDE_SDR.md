# Guide de configuration SDR

LUNATIC RADIO LAB accède au matériel via **SoapySDR** (recommandé) ou **GNU Radio / gr-osmosdr**. Ces
bibliothèques sont natives : elles s'installent avec le gestionnaire de paquets du système, pas avec `pip`.
Le script d'installation crée l'environnement virtuel avec `--system-site-packages` pour qu'elles soient visibles.

## 1. Matériel pris en charge (via SoapySDR)

| Matériel | Module SoapySDR | Plage indicative | Remarque |
|---|---|---|---|
| RTL-SDR (RTL2832U) | `rtlsdr` | 24 – 1766 MHz | ADC 8 bits, ≤ 2,4 MS/s stable |
| Airspy R2 / Mini | `airspy` | 24 – 1800 MHz | |
| Airspy HF+ | `airspyhf` | 0,5 kHz – 31 MHz, 60 – 260 MHz | |
| SDRplay RSP | `sdrplay` | 1 kHz – 2 GHz | API SDRplay requise |
| HackRF One | `hackrf` | 1 MHz – 6 GHz | sait émettre : **utilisé en réception seule** |
| LimeSDR | `lime` | 0,1 – 3800 MHz | idem |
| ADALM-PLUTO | `plutosdr` | 325 – 3800 MHz | idem |
| USRP B2xx | `uhd` | 70 – 6000 MHz | idem |

Les plages réelles sont lues dans le pilote ; le tableau n'est qu'indicatif.

## 2. Installation

### Debian / Ubuntu
```bash
sudo apt install python3-soapysdr soapysdr-tools soapysdr-module-rtlsdr   # + module de votre matériel
# optionnel : sudo apt install gnuradio gr-osmosdr ffmpeg
SoapySDRUtil --find        # doit lister le récepteur
```
Règles udev (RTL-SDR) : `sudo apt install rtl-sdr`, puis débrancher/rebrancher. Si le pilote noyau DVB-T
capture la clé : `echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/blacklist-rtl.conf`.

### Fedora
`sudo dnf install python3-SoapySDR SoapySDR rtl-sdr soapy-rtlsdr`

### macOS (Homebrew)
`brew install soapysdr soapyrtlsdr` — utilisez le Python de Homebrew pour le venv.

### Windows
Installez **PothosSDR** (inclut SoapySDR, modules et liaisons Python), cochez « ajouter au PATH », puis exécutez
`scripts\install.bat` avec un Python de même version que celle des liaisons PothosSDR. Pilote USB des clés RTL-SDR :
installer WinUSB avec Zadig.

## 3. Vérification

```bash
python -m lunatic_radio_lab devices
```
- « Connecté — pilote disponible » : prêt.
- « Connecté (USB) — pilote SDR absent » : le matériel est vu sur l'USB mais le module SoapySDR manque.
- Seulement « Récepteur simulé » : aucun récepteur ; l'application fonctionne en simulation.

Les récepteurs **réseau** (SoapyRemote, rtl_tcp) sont ignorés par défaut ; activation possible (protégée par
le code administrateur) dans « Équipements ».

## 4. Assistant de configuration

Écran « Équipements » → « Assistant de configuration » :
1. choix du récepteur, de la fréquence et de l'échantillonnage ;
2. compatibilité : plage de fréquences, échantillonnage, canaux autorisés couverts ;
3. test de réception (1 s) : débit effectif, plancher de bruit, saturation, composante continue ;
4. application.

## 5. Bonnes pratiques de mesure

- **Gain** : augmentez-le jusqu'à ce que le plancher de bruit monte de quelques dB, sans jamais déclencher
  l'indicateur « SATURATION ». En saturation, toutes les mesures sont faussées.
- **Raie DC** (RTL-SDR, HackRF…) : décalez légèrement la fréquence centrale ou utilisez « Exclusion DC ».
- **Correction ppm** : mesurez une porteuse de référence connue et corrigez l'écart.
- **Étalonnage dBm** : injectez un niveau connu avec un générateur étalonné, au même gain ; saisissez le
  décalage (Configuration récepteur). Il n'est valable que pour ce gain, cette fréquence et ce câblage.
- **Échantillonnage** : 250 kS/s couvre toute la bande PMR446 (200 kHz) ; augmentez pour observer plus large.

## 6. GNU Radio

Si `gnuradio` et `gr-osmosdr` sont installés, les périphériques trouvés par `osmosdr.device.find()` sont
listés (interface « gnuradio »). Ce pilote utilise un graphe *source → tampon* (réception seule). Il n'a pas été
validé sur matériel dans cette version : préférez SoapySDR.

## 7. Rejeu de fichiers IQ

« Configuration récepteur » → rejouer un fichier **SigMF** (`.sigmf-meta` + `.sigmf-data`) ou un fichier brut
(`cf32_le`, `ci16_le`, `cu8` de `rtl_sdr`). Les captures produites par l'application sont en SigMF, avec la
métadonnée `lrl:simulated` qui conserve la nature des données.
