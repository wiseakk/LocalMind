# Local interface fonts

Onest variable (100–900) and Unbounded variable (200–900), including Cyrillic,
are bundled as TTF files. Runtime requests go only to `/assets/fonts/`.
No font CDN or font service is contacted by the application.

Downloaded during development from the Google Fonts repository on 2026-10-28:

- [Onest metadata and source](https://github.com/google/fonts/blob/main/ofl/onest/METADATA.pb)
- [Unbounded metadata and source](https://github.com/google/fonts/blob/main/ofl/unbounded/METADATA.pb)

The original SIL Open Font License texts are `Onest-OFL.txt` and
`Unbounded-OFL.txt` beside these fonts. Attribution/copyright statements are
preserved there. Font files are unmodified. SHA-256 hashes are recorded in
`docs/evidence/constellation/local-assets.json` by `npm run check:assets -- --report`.
