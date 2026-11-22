# SortSmart V2 🌿

**AI-powered waste sorting for every Indian household.**

A fully responsive, production-grade single-page application built as one self-contained `index.html` — no build step, no npm, no server required.

---

## 🚀 Quick Start

### Option 1 — Double-click (simplest)
Just open `index.html` in any modern browser:
```
double-click index.html
```

### Option 2 — Local HTTP server (recommended for full feature parity)
```bash
cd /Users/jatingarg/Desktop/SortSmartV2
python3 -m http.server 3000
```
Then open: **http://localhost:3000**

### Option 3 — Node.js
```bash
npx serve .
```

---

## 📦 What's Inside

```
SortSmartV2/
└── index.html      # The entire app — all HTML, CSS, and JSX in one file
└── README.md       # This file
```

---

## 🌟 Features

| Section | Description |
|---|---|
| **Navbar** | Sticky nav with logo, links, points badge, dark mode, language selector (EN/HI/PA), mobile hamburger drawer, bottom tab bar |
| **Hero** | Headline, subhead, 4 category chips (WET/DRY/SANITARY/SPECIAL CARE), dual CTAs |
| **Scan Item** | Photo upload (drag-drop) + text mode, skeleton loaders, result card with stream badge + confidence bar + steps, ScrapUncle Hub with 4 tabs |
| **Sell Scrap** | 4 tabs: Live Prices (20 items), Calculator, Book Pickup (form), My Requests (timeline); trust badges; city + category filters |
| **Govt Schemes** | 3 cards: Swachh Bharat Urban 2.0, Mission LiFE, CPCB EPR — each with benefit checklists and external links |
| **Discounts** | Wallet balance, 4 voucher cards with redeem logic (disabled when insufficient points), copy-to-clipboard coupon codes |
| **Certificate** | Decorative certificate preview, locked overlay until monthly goal met, Print + Download buttons |
| **Rewards & Goals** | Points rules, weekly + monthly progress bars, Claim Bonus buttons, confetti animation on claim |
| **Impact Dashboard** | 4 stat cards, CSS donut chart for category distribution, empty state CTA |
| **Footer** | Logo, tagline, disclaimer |

---

## 🛠 Tech Stack (CDN only)

| Library | Version | Purpose |
|---|---|---|
| React | 18 (UMD) | UI framework |
| ReactDOM | 18 (UMD) | DOM rendering |
| Babel Standalone | latest | JSX → JS in browser |
| Tailwind CSS | CDN | Utility-first styling |
| Lucide Icons | latest (UMD) | SVG icon system |

---

## 🎨 Design System

Custom Tailwind colors:
- `primary` — #2E7D32 (deep green)
- `accent` — #E8742A (warm orange)
- `dry` — #1565C0 (blue, dry waste)
- `wet` — #2E7D32 (green, wet/organic)
- `ewaste` — #C62828 (red, e-waste/special care)
- `sanitary` — #E65100 (amber, sanitary waste)

---

## 💾 localStorage Keys

| Key | Contents |
|---|---|
| `ss_dark` | Dark mode preference (boolean) |
| `ss_points` | User's total points (number) |
| `ss_lang` | Language preference (EN/HI/PA) |
| `ss_history` | Scan history array (last 100 items) |
| `ss_week_claimed` | Weekly bonus claimed flag |
| `ss_month_claimed` | Monthly bonus claimed flag |

---

## ⚠️ Disclaimer

> Sorting guidance is a prototype, not an official municipal ruling. Always verify with your local municipal authority.

---

## 📄 License

MIT — free to use, modify, and distribute.
