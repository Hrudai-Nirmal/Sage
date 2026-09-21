# Sage public compliance site

## Purpose

This static site supplies the public homepage, privacy policy, and terms required for Sage's Google OAuth configuration at `sage.hrudainirmal.in`.

## Key decisions

- The site is disclosure-only. It has no forms, application runtime, tracking scripts, cookies, or connection to Sage's local services.
- Google data remains in the local Sage system; the Vercel-hosted pages never receive it.
- Canonical public routes are `/`, `/privacy`, and `/terms` through Vercel clean URLs.
- The privacy policy names Gmail, Google Calendar, and Google Drive access and includes Google's Limited Use disclosure.
- The public contact is `hrudainirmalwork@gmail.com` unless the owner explicitly replaces it.
- The site uses a restrained technical design with system fonts and local assets only.

## Deployment

Deploy this directory as its own Vercel project and bind `sage.hrudainirmal.in`. Hostinger already routes wildcard subdomains to Vercel; Google Search Console domain verification still requires Google's TXT record at the DNS provider.
