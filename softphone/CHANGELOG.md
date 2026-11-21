# NIMBORA Softphone — journal des versions

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
