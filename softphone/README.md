# NIMBORA Softphone

Votre poste téléphonique d'entreprise sur **Windows, macOS, Linux, Android, iPhone/iPad** et dans
**le navigateur** — une seule application, à la marque de la plateforme.

- Appels entrants et sortants sur le PBX d'entreprise (SIP sur WebSocket sécurisé, audio WebRTC
  chiffré SRTP), sonnerie et notification, numéro ou nom de l'appelant.
- En appel : micro coupé, attente, clavier (DTMF), **transfert**, durée ; un second appelant reçoit
  « occupé ».
- **Récents** (journal du PBX, appels manqués en rouge), **Contacts** (collègues, groupes et files,
  recherche sans accents), **messagerie vocale** en un bouton.
- **Ne pas déranger** et **renvoi de tous les appels** depuis l'application.
- Choix de la sortie audio, clavier physique sur ordinateur, thème clair ou sombre.

## Jumelage

1. Dans la console : **Téléphonie d'entreprise → Postes → Softphone** sur le poste de la personne.
2. Un **code à usage unique** (valable 15 minutes) s'affiche, avec un **QR code**.
3. Sur l'appareil : scanner le QR code (le lien `nimbora-softphone://` ouvre l'application), ou
   saisir l'adresse de la plateforme et le code.

L'appareil reçoit un **jeton d'appareil** (seule son empreinte est conservée côté plateforme). Le
mot de passe SIP n'est **jamais stocké** sur l'appareil ni dans la plateforme : il est lu sur le PBX à
chaque démarrage. Révoquer un appareil (console → Postes → Softphones) le coupe aussitôt ; supprimer un
poste révoque tous ses appareils.

Le poste doit avoir une **ligne navigateur (WebRTC)** — c'est le cas des postes créés avec
« Ligne : navigateur ».

## Architecture

```
softphone/
├── src/                  # l'application (React + JsSIP), identique sur toutes les plateformes
│   ├── lib/api.ts        # API /api/v1/softphone/* (jeton d'appareil)
│   ├── lib/phone.ts      # agent SIP, états d'appel (réducteur testé)
│   ├── lib/native.ts     # liens de jumelage, notifications, sonnerie (Web Audio)
│   └── components/       # jumelage, clavier, appel, récents, contacts, réglages
├── public/               # icônes, manifeste PWA, service worker
├── src-tauri/            # coque native Tauri 2 (Windows, macOS, Linux, Android, iOS)
└── scripts/              # icônes, permissions Android
```

| Plateforme | Paquet | Construit par |
|---|---|---|
| Navigateur (PWA installable) | `dist/` | `npm run build` |
| Windows | `.msi`, `.exe` (NSIS) | CI `softphone.yml` |
| macOS (Intel + Apple Silicon) | `.dmg`, `.app` | CI (signature et notarisation si les secrets Apple sont fournis) |
| Linux | `.deb`, `.rpm`, `.AppImage` | CI, ou `npx tauri build` |
| Android | `.apk` | CI (`tauri android build`) |
| iOS | `.app` (simulateur) | CI ; TestFlight/App Store avec un certificat Apple |

## Développement

```bash
cd softphone
npm install
npm test              # tests (format, API, téléphone, application)
npm run dev           # http://localhost:5175
npx tauri dev         # application de bureau (Rust + dépendances WebKitGTK sous Linux)
npx tauri build       # paquets pour le système courant
```

Sous Linux : `libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev libxdo-dev patchelf`.
Le paquet `.deb` (≈ 2 Mo, dépend de `libwebkit2gtk-4.1-0` et `libgtk-3-0`) a été construit et
lancé sur Ubuntu. Son raccourci (`nimbora-softphone.desktop`) déclare le schéma
`nimbora-softphone://` avec `Exec=… %u`, pour qu'un lien d'activation ouvre l'application.

Une version publiée se fait en poussant un tag `softphone-vX.Y.Z` : la CI crée un brouillon de
release avec les paquets de bureau, l'APK Android et la version iOS de test.

## Limites actuelles

- **Appels entrants application fermée** sur mobile : ils demandent des notifications push VoIP
  (PushKit / FCM) relayées par la plateforme — prévu. Aujourd'hui, les appels arrivent quand
  l'application est ouverte ; sur ordinateur, elle peut rester réduite.
- Une seule communication à la fois (le second appelant entend « occupé ») ; le transfert est un
  transfert direct (sans consultation).
