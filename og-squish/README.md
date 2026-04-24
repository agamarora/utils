# og-squish

Squish PNG/JPG Open Graph images to 1200×630 + web-safe file sizes. Offline. Zero config.

## Why

OG images need three things:
- Exact **1200×630** (or social platforms crop or reject)
- Under **~300 KB** (fast preview cards)
- **PNG or JPG** — WebP is unreliable across LinkedIn, iMessage, older OG scrapers

Most image tools either require a GUI, ship as a SaaS, or need a Docker container. og-squish is a 100-line Node script.

## Install

```bash
git clone https://github.com/agamarora/utils.git
cd utils/og-squish
npm install
```

## Use

```bash
# squish every PNG/JPG in a folder (in place)
node optimize.mjs /path/to/og-images/

# dry run — report savings without writing
node optimize.mjs /path/to/og-images/ --dry
```

Output:

```
og-squish — /site/assets/og
target: 1200x630, <300 KB

  landing.png              2780 KB ->    189 KB  (-93%)
  lab.png                   750 KB ->    142 KB  (-81%)
  second-brain.png          757 KB ->    156 KB  (-79%)
  ai-resume.png             751 KB ->    148 KB  (-80%)

total: 5038 KB -> 635 KB (-87%)
```

## What it does

- Resizes to 1200×630 with `fit: cover` (enforces OG spec)
- PNG: `compressionLevel: 9`, palette quantization, max effort
- JPG: `quality: 85`, mozjpeg, progressive
- Flags any file still over 300 KB after optimization

## License

MIT — see [LICENSE](../LICENSE).
