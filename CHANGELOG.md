# Changelog — NIMBORA

## 1.0.0 (2026-11-20)

### Plateforme
- SaaS multi-entreprises : offres, abonnements, essai gratuit, quotas de minutes,
  limites par client, Stripe (Checkout, portail, webhooks signés), console opérateur.
- IA souveraine : provisionnement automatique Ollama + Speaches pour chaque entreprise,
  packs de langues (Whisper ~100 langues, voix Kokoro et Piper).
- Centre d'appels humain : files d'attente et postes Asterisk par entreprise,
  softphone WebRTC, transfert IA → humain (`queue:<nom>`).
- Déploiement VPS en une commande (Caddy HTTPS, Asterisk, coturn, Ollama, Speaches),
  sauvegarde et restauration.
- Sécurité : isolation entre entreprises, protection SSRF, refus des secrets faibles.

### Interface
- Identité visuelle NIMBORA : logo, favicon, thème « Aurora », interfaces animées,
  polices auto-hébergées.
