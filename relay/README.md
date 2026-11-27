# Voice relay (Cloudflare Worker)

Microsoft's Edge read-aloud service rejects connections from websites, so the iPad/iPhone web app
reaches Francisca, Thalita and Antônio through this small Worker. It speaks the same protocol as
`edge-tts` (including the `Sec-MS-GEC` v2 token, ported in `gec.js` and checked against Python),
returns an MP3, only accepts requests from the Ronic Reader site and only those three voices.

```bash
cd relay
npx wrangler login     # once
npx wrangler deploy    # publishes ronic-reader-vozes.<subdomain>.workers.dev
npx wrangler dev       # local test on http://127.0.0.1:8787
```

`worker-colar.js` is the same code in a single file, for pasting into the Cloudflare dashboard.
The web app reads the address from `RELAY` in `ios-web/backend.js`. Free plan: 100,000 requests a day.
