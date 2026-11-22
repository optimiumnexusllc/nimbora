# NIMBORA Softphone — journal des versions

## 1.4.0 — 22 novembre 2026

**Interception, parcage et interphone.**

- **Intercepter** (clavier) : compose le code d'interception (`*8`) pour décrocher un appel qui
  sonne chez un collègue du même groupe d'interception.
- **Parquer** (panneau Transférer) : l'appel attend sur une place du parking ; **Récents →
  Appels parqués** liste les appels en attente avec leur place et leur durée, un appui les
  reprend (actualisé toutes les 10 s).
- **Interphone et annonces** : un appel d'interphone (`*11…`) est décroché automatiquement par
  l'application et affiché « Interphone ».

## 1.3.0 — 22 novembre 2026

**Transfert avec consultation et conférence à trois.**

- **Transférer → Appeler d'abord** : le client est mis en attente et l'application appelle le
  collègue (les collègues disponibles sont proposés). Pendant la consultation :
  - **Basculer** entre le client et le collègue ;
  - **Transférer** : le PBX relie le client au collègue et l'employé se retire (transfert
    assisté, REFER avec Replaces) ; si le collègue n'a pas encore décroché, le PBX l'appelle pour
    le client ;
  - **Conférence** : les trois s'entendent, mixage dans l'application ; le micro coupé l'est pour
    les deux appels ; **Se retirer** laisse le client et le collègue ensemble ;
  - **Annuler** (ou le bouton rouge) raccroche avec le collègue et reprend le client.
- Si le client raccroche pendant la consultation, l'appel du collègue continue
- Dès que le PBX a relié le client et le collègue (transfert ou « Se retirer »), l'application
  raccroche elle-même ses deux appels : le poste est libre immédiatement au lieu d'attendre le
  raccroché du PBX (validation en laboratoire, étape 14). normalement.
- **Transférer directement** reste disponible (transfert aveugle).

## 1.2.1 — 22 novembre 2026

- Après « Régénérer le mot de passe SIP » dans la console, l'application relit son compte dès
  que le PBX refuse l'ancien secret et redémarre la ligne avec le nouveau : aucun rejumelage.
  Une seule nouvelle lecture par refus, jamais pendant un appel.

## 1.2.0 — 22 novembre 2026

**Qui est disponible, et tous vos contacts au même endroit.**

- **Présence des collègues** dans Contacts : disponible, en appel, sonne, ne pas déranger, absent
  ou hors ligne, avec leur message (« En réunion jusqu'à 15 h ») ; nombre de collègues
  disponibles ; actualisé toutes les 20 secondes tant que l'onglet est ouvert.
- **Ma présence** dans Réglages : Disponible, Absent ou Hors ligne, avec un message. En appel,
  sonnerie et ne pas déranger suivent le poste automatiquement.
- **Annuaire unifié** : collègues, services (groupes et files) et **clients** de la mémoire
  client (clients récents, recherche par nom ou numéro sur le serveur, badge VIP, conseiller
  habituel). Un appel entrant d'un client connu affiche son nom.
- Nécessite NIMBORA avec le droit de présence du compte de service ; sans lui, l'application
  montre seulement qui est en appel.
- **Correctif** : l'application s'enregistre avec l'identité SIP du poste et s'authentifie avec
  son nom SIP (`sip_identity` dans la configuration). Avant, le moteur 26.11 refusait les
  identifiants d'un poste navigateur alors que le mot de passe était le bon.
- « Hors ligne » choisi dans Ma présence reste « Hors ligne » même téléphone enregistré.

## 1.1.0 — 21 novembre 2026

**Les appels transférés par l'agent IA arrivent avec leur contexte.**

- **Fiche de passation à la sonnerie** : quand un agent IA transfère un client vers une file ou un
  poste du PBX, l'application affiche dès la sonnerie, puis pendant l'appel, le motif de l'appel,
  un résumé, l'humeur du client, la prochaine étape conseillée, les informations recueillies
  (budget, adresse, date…) et la conversation avec l'IA. Le conseiller ne fait plus répéter le
  client.
- Décrocher marque la fiche comme prise en charge (visible en supervision).
- Le client est reconnu que l'opérateur présente son numéro en format national ou international.
- Thèmes clair et sombre pour la fiche.
- Paquets vérifiés sur la CI pour Windows (`.msi`, `.exe`), macOS universel (`.dmg`), Linux
  (`.deb`, `.rpm`, `.AppImage`), Android (`.apk`), iOS (simulateur) et le navigateur (PWA).

## 1.0.0 — 21 novembre 2026

Première version : le poste d'entreprise sur Windows, macOS, Linux, Android, iPhone/iPad et dans le
navigateur.

- Appels entrants et sortants (SIP sur WebSocket sécurisé, audio WebRTC chiffré), sonnerie et
  notification ; micro coupé, attente, clavier (DTMF), transfert.
- Récents, contacts (collègues, groupes, files), messagerie vocale en un bouton.
- Ne pas déranger et renvoi de tous les appels depuis l'application.
- Jumelage par QR code ou code à usage unique ; mot de passe SIP jamais stocké ; révocation par
  appareil.
