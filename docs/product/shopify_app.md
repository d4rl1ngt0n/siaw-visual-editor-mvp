# Siaw Shopify app (merchant installable)

Siaw is two surfaces that share one core:

1. **Web product**: anyone can use Siaw as a normal website builder.
2. **Shopify app**: merchants add Siaw to their store from Shopify Admin (Apps), the same way they install other Shopify apps.

This is not a private tool for one developer account. Any merchant who installs the app gets App Home inside Shopify Admin, catalog access, and a path into the Siaw editor.

## Merchant flow

1. Merchant finds Siaw in the Shopify App Store (or a custom install link / Partners install).
2. They click **Add app** / **Install**.
3. Shopify shows consent for Admin API scopes.
4. Shopify opens **App Home** at `/shopify/app/?shop=...&host=...`.
5. App Bridge issues a short-lived session token; the app exchanges it for an offline Admin API token and stores the install on `ShopifyShop`.
6. Merchant clicks **Build site from catalog** to seed an AI brief and continue in Siaw.

## Web product flow (optional)

Sellers who already use the Siaw website can also connect a store from Account → Shopify. That uses the same OAuth callback and `ShopifyShop` row, and can link a Siaw login to an install.

## Environment

```bash
SHOPIFY_API_KEY=...
SHOPIFY_API_SECRET=...
SHOPIFY_API_VERSION=2025-10
SHOPIFY_SCOPES=read_products,read_product_listings,read_files,read_themes
SHOPIFY_APP_URL=https://your-public-https-origin
```

`SHOPIFY_APP_URL` must be a public https origin (Render, tunnel, etc.).

## Partner / CLI setup

1. Create an app in Shopify Partners (or Dev Dashboard).
2. Set **App URL** to `{SHOPIFY_APP_URL}/shopify/app/`.
3. Enable **Embed app in Shopify admin**.
4. Allowed redirection URLs:
   - `{SHOPIFY_APP_URL}/shopify/callback/`
   - `{SHOPIFY_APP_URL}/shopify/auth/`
5. Scopes: `read_products`, `read_product_listings`, `read_files`, `read_themes`.
6. Webhooks:
   - `app/uninstalled` → `/shopify/webhook/`
   - compliance: `customers/data_request`, `customers/redact`, `shop/redact` → `/shopify/webhook/`
7. Copy API key / secret into `.env`.
8. Keep `shopify.app.toml` `client_id` + URLs in sync with `.env`, then push:

```bash
set -a && source .env && set +a
shopify app deploy --client-id "$SHOPIFY_API_KEY" --force
```

## Local merchant install test

1. Run Django: `.venv/bin/python manage.py runserver 127.0.0.1:8000`
2. Tunnel it: `ngrok http 8000`
3. Put the ngrok https origin into `SHOPIFY_APP_URL`, `ALLOWED_HOSTS`, and `CSRF_TRUSTED_ORIGINS` in `.env`
4. Mirror that host in `shopify.app.toml` `application_url` + `redirect_urls`
5. Deploy config (`shopify app deploy` above)
6. Install on a development store with either:
   - Partners → Apps → Siaw → **Test on development store**, or
   - `https://admin.shopify.com/oauth/install_custom_app?client_id=YOUR_SHOPIFY_API_KEY`
7. After install, App Home opens at `/shopify/app/` inside Shopify Admin

Public App Store listing still needs listing assets + Shopify review. Until then, use custom / Partners install links.

## Routes

| Path | Purpose |
| --- | --- |
| `/shopify/app/` | Embedded App Home (merchant UI) |
| `/shopify/auth/` | Install entry (`?shop=`) |
| `/shopify/callback/` | OAuth authorization code return |
| `/shopify/session/` | Session token → offline access token exchange |
| `/shopify/app/products/` | Catalog JSON (session auth) |
| `/shopify/app/build/` | Seed AI brief from catalog (session auth) |
| `/shopify/webhook/` | Uninstall + compliance webhooks |
| `/shopify/connect/` | Optional: connect from Siaw Account |

## Security notes

- App Home allows framing only from `admin.shopify.com` and `*.myshopify.com`.
- Session JWTs are verified with HMAC-SHA256 using `SHOPIFY_API_SECRET`.
- Access tokens are encrypted at rest before storage.
- One `ShopifyShop` row per `shop_domain` (the merchant install).

## Next

- App Store listing assets and billing
- Theme app extensions / Online Store blocks
- Deeper checkout and product sync
- Stronger compliance webhook data handling
