# Brand folder (white label)

Put your logo, favicon and font here. They are mounted read-only into the
interface container (`/brand`) and served as `/brand-assets/<file>`:
images (`.svg`, `.png`, `.jpg`, `.webp`, `.ico`) and fonts (`.woff2`, `.woff`).

Then point the charter at them in `.env` and restart the stack:

```bash
BRAND_NAME="Acme Voix"
BRAND_LOGO_URL=/brand-assets/logo.svg
BRAND_LOGO_DARK_URL=/brand-assets/logo-dark.svg
BRAND_FAVICON_URL=/brand-assets/favicon.png
BRAND_PRIMARY_COLOR=#0a7d4f
```

Everything else is in `docs/deployment/white-label.mdx`. Files other than this
README are ignored by git.
