# Conformité légale — réception, enregistrement et usage des fréquences

> Ce document résume des principes généraux et cite des textes de référence à titre indicatif. **Il ne constitue
> pas un avis juridique.** Les textes évoluent : vérifiez la version en vigueur auprès de l'autorité compétente
> du pays d'utilisation avant toute mise en service.

## 1. Principes communs à la plupart des juridictions

1. **Recevoir n'autorise pas à exploiter.** Le fait qu'une émission soit captable ne donne pas le droit
   d'enregistrer, de divulguer ou d'utiliser le contenu de communications qui ne vous sont pas destinées.
2. **Secret des correspondances.** Les communications privées et professionnelles (dont les réseaux PMR/DMR/P25
   d'entreprises, de services de secours ou de sécurité) sont protégées.
3. **Pas de contournement du chiffrement**, même faible ou « par défaut ».
4. **Émission soumise à autorisation.** L'utilisation d'une fréquence en émission requiert une licence ou un
   cadre d'exemption (ex. PMR446). Ce logiciel n'émet pas.
5. **Matériel conforme.** Les récepteurs doivent être utilisés conformément à leur marquage et à leur notice.

## 2. Mise en œuvre dans le logiciel

| Exigence | Mesure technique |
|---|---|
| Pas d'émission | Aucune fonction d'émission ; flux SoapySDR/GNU Radio en réception uniquement ; test automatisé qui interdit ces motifs dans le code |
| Pas de déchiffrement | Aucun décodeur de voix numérique ni de trame ; caractérisation physique et repérage des motifs de synchronisation publics (séquences fixes sans information) seulement |
| Enregistrement encadré | Démodulation/capture IQ réelles limitées aux canaux marqués « enregistrement autorisé » avec référence d'autorisation, attestation de l'opérateur et audit |
| Traçabilité | Journal d'audit horodaté (accès, configuration, imports, exports, captures, refus) |
| Local par défaut | Aucun appel réseau ; récepteurs réseau désactivés par défaut (activation protégée) |
| Pas de listes sensibles | Seul le plan PMR446 public est fourni ; l'administrateur saisit ses propres canaux autorisés |

## 3. France (et Union européenne)

- **Code pénal, art. 226-15** : réprime le fait, de mauvaise foi, d'intercepter, de détourner, d'utiliser ou de
  divulguer des correspondances émises, transmises ou reçues par voie électronique, ainsi que l'installation
  d'appareils conçus pour réaliser de telles interceptions. Les **art. 226-3** et **R. 226-1 s.** encadrent la
  fabrication, la détention et la mise sur le marché de certains appareils d'interception (autorisations
  délivrées par le Premier ministre / ANSSI) : vérifiez si votre usage ou votre configuration matérielle
  relève de ce régime.
- **Code des postes et des communications électroniques (CPCE)** : principe du secret des correspondances
  pour les opérateurs (art. L. 32-3) ; gestion et assignation des fréquences par l'**ANFR** ; autorisations
  d'utilisation de fréquences délivrées par l'**ARCEP** ou les affectataires.
- **PMR446** : utilisation sans licence de 446,0–446,2 MHz pour les équipements conformes (décision CEPT
  **ECC/DEC/(15)05**, puissance apparente rayonnée maximale 500 mW, antenne intégrée), transposée par décision
  nationale : vérifiez la version applicable.
- **RGPD** : un enregistrement de voix est une donnée personnelle ; base légale, durée de conservation,
  information des personnes et sécurité des données doivent être assurées.
- **Directive 2014/53/UE (RED)** : conformité des équipements radio mis sur le marché.

## 4. Autres juridictions (points de vigilance)

- **Belgique** : IBPT (gestion du spectre) ; secret des communications (loi du 13 juin 2005, art. 124).
- **Suisse** : OFCOM ; secret des télécommunications (LTC) et art. 179 s. du Code pénal.
- **Canada** : ISDE (gestion du spectre) ; Loi sur la radiocommunication (art. 9) et Code criminel (art. 184)
  sur l'interception et la divulgation.
- **États-Unis** : FCC ; 47 U.S.C. § 605 et Electronic Communications Privacy Act (18 U.S.C. § 2511). PMR446
  **n'est pas autorisé** (les services FRS/GMRS en tiennent lieu).
- **Afrique francophone** (ex. Tchad : ARCEP Tchad ; Sénégal : ARTP ; Côte d'Ivoire : ARTCI ; Cameroun :
  ART/ANTIC) : les régimes de licence et de secret des correspondances sont définis par les lois nationales
  sur les communications électroniques ; l'usage de bandes de type PMR446 n'y est pas nécessairement autorisé.
  Consultez le régulateur.

## 5. Recommandations d'usage

1. Documentez l'autorisation de chaque canal (licence, convention avec le propriétaire du réseau, ordre de
   mission de maintenance, agrément de laboratoire) dans « Canaux autorisés ».
2. N'activez l'enregistrement audio que lorsque l'autorisation le prévoit explicitement.
3. Conservez les rapports et le journal d'audit pour justifier les opérations.
4. Pour les essais, privilégiez le **mode laboratoire**, une charge fictive et des signaux de test
   (générateur RF en conduit, cage de Faraday).
5. Supprimez les enregistrements dès qu'ils ne sont plus nécessaires.
