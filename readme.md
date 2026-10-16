# FAWZIKO — Premium portfolio

A redesign of the supplied FAWZIKO HTML, inspired by the cinematic direction in Sitios Web Premium.pdf. Plain HTML, CSS and JavaScript, with locally bundled GSAP and ScrollTrigger. No build step or frontend framework.

## Deploy

Extract the contents of the ZIP directly into `public_html` (index.html must be at the root). Keep the assets folder, app.js, style.css and .htaccess together. All file paths are relative and lowercase. The included Apache configuration adds media MIME types and range-response headers. Apache handles actual byte-range requests for static video files.

## Run locally

From this directory: `python -m http.server 3000`. Visit http://localhost:3000.

## Single-file edition

The separately delivered `index.html` outside this project folder embeds all fonts, images, CSS and JavaScript. You can open it directly in a browser or upload it alone. The ZIP edition is easier to maintain and benefits from separately cached assets.

## Included

- Full-screen, sticky scroll-led hero with smoothly interpolated camera-art scale, rotation, perspective and text transitions.
- A newly generated conceptual camera visual, optimized into desktop and mobile WebP versions. This artwork is decorative and is not presented as a client project or the creator's own equipment.
- Actual stills retrieved from the original portfolio's Vimeo videos, rather than invented client-work images.
- Nine project entries and all 14 original Vimeo video links, including the two original unlisted-video hashes.
- Category filters, expandable project list, multi-clip video galleries and native accessible dialog behavior (Escape, focus return and keyboard containment).
- Responsive navigation, capability accordions, project-type selection and HTML form validation.
- Reduced-motion mode, local fonts, lazy-loaded project images and CDN fallback for the locally bundled animation libraries.
- Original email, WhatsApp and Instagram destinations.

## Important scope differences from the reference PDF

The PDF is an AI product-launch recipe, not an existing Sirius website template. Its art direction and scroll-led presentation were adapted to a creator portfolio. No Higgsfield, Kling/Seedance video generation or 4K upscaling was performed. The hero animates an original still image; it is NOT a generated 3D video or video-time scrubbing implementation. Project films remain available on demand in a dialog, instead of removing them to satisfy the reference's single-video rule.

The contact form prepares an email using `mailto:`. It does not submit to a backend or confirm delivery. Visitors must complete sending in their email client. Direct email and WhatsApp links are also available.

## Network access

Fonts, animation libraries, hero art and project thumbnails are bundled locally. Playing a project requires an internet connection to Vimeo. Third-party player privacy settings, video availability or browser policies can affect playback. The embedded file viewer may block remote videos; use the live preview or a normal browser.

## Editing

- Content/layout: index.html
- Colors, typography, responsive layout: style.css (`:root`)
- Project video IDs/hashes, filter logic, hero motion, brief choices: app.js
- Hero master: assets/images/hero-master.png
- Optimized artwork: assets/images/hero.webp and hero-mobile.webp
- Project stills: assets/images/work-[video-id].webp
- Preserved source-brand logos: assets/images/brand-*.webp

## Browser checks

Tested using Chromium at desktop and mobile sizes: project filtering, 4-to-9 expansion, video iframe destinations, dialog close with Escape, mobile navigation, brief selector, scroll transform and reduced-motion rendering. No page JavaScript errors were observed in these checks. Vimeo playback itself depends on its external service; no claim is made that every film was played through. No claim is made of testing the PDF's unavailable 4K media-generation steps.

## Latest photo and icon correction

The About portrait is the exact user-supplied photo (04CFAE7E-0660-494F-ABD4-B12109C92C81.jpeg), converted to WebP for embedding without generating or synthesizing any new image. Its original warm lighting is retained. Dulingo and Kitchow preview photos were replaced with the existing brand logos; all original video IDs, unlisted hashes and player functions are unchanged. Emoji-like icon characters were replaced with inline SVG vectors. No new image generation was performed for this correction.
