# SortSmart V2 🌿
**AI-Powered Waste Sorting & Recycling Rewards Platform for Indian Households**

A production-grade, responsive single-page web app built with React 18, Tailwind CSS, and Lucide SVG icons. Fully connected to the SortSmart AI classification and ScrapUncle pickup database backend.

---

## 🚀 Live Access URLs

| Device / Environment | SortSmart V2 (React UI) | SortSmart V1 (AI Backend & Admin) |
|---|---|---|
| **Local Desktop** | [http://localhost:3000](http://localhost:3000) | [http://localhost:8000](http://localhost:8000) |
| **Mobile Phone (LAN WiFi)** | `http://10.57.5.44:3000` | `http://10.57.5.44:8000` |

> *Note: For mobile phone access, make sure your mobile device is connected to the same Wi-Fi network as your Mac.*

---

## 📦 Project Structure

```
SortSmartV2/
├── index.html         # Complete single-page application (React 18 + Tailwind + Lucide)
├── data/
│   └── prices.json    # Mandi benchmark scrap prices (Delhi NCR, Punjab, etc.)
└── README.md          # System documentation & setup guide
```

---

## 🔗 Architecture & Database Integration

```
  ┌─────────────────────────────────────────────────────────┐
  │        SortSmart V2 Frontend (React SPA, Port 3000)      │
  │   - Scan Item (Photo & Text modes)                      │
  │   - Sell Scrap (Live Mandi Prices, Calculator, Booking) │
  │   - Rewards & Goals (+ Confetti Animation)              │
  │   - Mission LiFE Green Citizen Certificate              │
  │   - Dark Mode & Multi-language (EN / HI / PA)           │
  └───────────┬─────────────────────────────────┬───────────┘
              │                                 │
              ▼                                 ▼
   [ Flask AI Backend (Port 8000) ]     [ Client-side Cache ]
   ├── POST /api/analyze                ├── ss_points
   │   └── Dual AI Engine (Groq/Ollama) ├── ss_history
   ├── POST /api/scrapuncle/book-pickup ├── ss_pickups
   │   └── Saves to `pickups.json`      ├── ss_dark
   └── GET  /api/scrapuncle/pickups     └── ss_lang
       └── Reads from `pickups.json`
```

### 1. Real AI Backend Classification
- **Endpoint**: `POST /api/analyze`
- Supports both **Photo upload** (`image` file, multipart) and **Text description** (`description` string).
- Automatically normalizes categories into Indian municipal waste streams: `DRY` (Blue), `WET` (Green), `SANITARY` (Amber), and `SPECIAL CARE / E-WASTE` (Red).
- If the backend is temporarily unreachable, V2 automatically falls back to an offline mock dataset with clear toast notifications.

### 2. Doorstep Scrap Pickup Database (`pickups.json`)
- **Booking Endpoint**: `POST /api/scrapuncle/book-pickup`
- Books a verified doorstep scrap collection with full customer details (Name, Phone, Address, Slot, Payment mode).
- Generates a real booking tracking code (e.g. `SU-303756`).
- **Persistence**: Saved directly to `pickups.json` on the server and cached in `localStorage` (`ss_pickups`).
- **My Requests Tracking**: Real-time sync with `/api/scrapuncle/pickups` displays pending, scheduled, and completed requests across both desktop and mobile sessions.
- **Eco Points Bonus**: Automatically awards **+25 Eco Points** per confirmed pickup.

---

## 🛠 Local Development & Server Setup

### Start the V2 Web Server (Port 3000):
```bash
cd /Users/jatingarg/Desktop/SortSmartV2
python3 -m http.server 3000 --bind 0.0.0.0
```

### Start the V1 AI & Database Backend (Port 8000):
```bash
cd /Users/jatingarg/Desktop/SortSmart
.venv/bin/python web_app.py --host 0.0.0.0 --port 8000
```

---

## 🌟 Key Features

1. **AI Waste Identification**: High-accuracy stream categorization with actionable disposal steps and material specifications.
2. **Instant ScrapUncle Hub**: Live mandi price benchmark, dynamic scrap value calculator, doorstep pickup scheduler, and request status timeline.
3. **Government Schemes Integration**: Information cards for Swachh Bharat Urban 2.0, Mission LiFE (P3), and CPCB EPR compliance.
4. **Discounts & Coupons**: Redeemable vouchers for groceries, eco goods, EV/metro credits, and scrap bonuses.
5. **Mission LiFE Certificate**: Dynamic Green Citizen certificate with print-to-PDF support, unlocked after monthly waste sorting targets.
6. **Zero External Build Tools**: Runs smoothly straight from CDN scripts (React 18 UMD, Babel Standalone, Tailwind CDN, Lucide UMD) without needing `npm` or `node`.

---

## ⚠️ Disclaimer

Sorting guidance is a prototype designed for household education and circular economy awareness, not an official municipal ruling. Always verify specific segregation rules with your local urban local body (ULB).

---

## 📄 License
MIT License — Created for SortSmart.
