# Enhanced Scrap Rates & Categories based on Delhi-NCR & India Mandi Benchmarks

SCRAP_CATEGORIES = {
    "paper": {
        "title": "Paper & Cardboard",
        "icon": "📄",
        "items": [
            {"id": "newspaper", "name": "Newspaper (Akbar)", "rate": 16, "unit": "kg", "note": "Clean, dry sheets bundled", "trend": "+₹1 today"},
            {"id": "cardboard", "name": "Cardboard (Gatta / Carton)", "rate": 14, "unit": "kg", "note": "Flattened corrugated packaging boxes", "trend": "Stable"},
            {"id": "books", "name": "Old Books & Notebooks", "rate": 14, "unit": "kg", "note": "Textbooks, copies without plastic spiral", "trend": "High demand"},
            {"id": "magazines", "name": "Office Paper & Magazines", "rate": 15, "unit": "kg", "note": "White A4 papers, shredded sheets", "trend": "Stable"}
        ]
    },
    "plastics": {
        "title": "Plastics & Containers",
        "icon": "🧴",
        "items": [
            {"id": "pet_bottles", "name": "PET Bottles (Water / Soda)", "rate": 15, "unit": "kg", "note": "Transparent crushed beverage bottles", "trend": "High demand"},
            {"id": "hard_plastic", "name": "Hard Plastic (Buckets / Chairs)", "rate": 18, "unit": "kg", "note": "Broken HDPE/PP chairs, crates, tubs", "trend": "+₹2 today"},
            {"id": "mix_plastic", "name": "Mixed Household Plastic", "rate": 10, "unit": "kg", "note": "Clean polythene, packaging wraps", "trend": "Stable"},
            {"id": "milk_pouches", "name": "Milk Pouches (Rinsed)", "rate": 12, "unit": "kg", "note": "Washed, completely dried pouches", "trend": "Stable"}
        ]
    },
    "metals": {
        "title": "Metals & Alloys",
        "icon": "🔩",
        "items": [
            {"id": "copper", "name": "Pure Copper Wire / Utensils", "rate": 540, "unit": "kg", "note": "Stripped electrical copper wire & brass pots", "trend": "🔥 Top Value"},
            {"id": "brass", "name": "Brass (Peetal) Scrap", "rate": 350, "unit": "kg", "note": "Taps, statues, heavy vessels", "trend": "+₹5 today"},
            {"id": "aluminum", "name": "Aluminum Utensils / Cans", "rate": 120, "unit": "kg", "note": "Beverage cans, window sections", "trend": "Stable"},
            {"id": "iron", "name": "Iron / Loha (Heavy & Light)", "rate": 34, "unit": "kg", "note": "Rods, pipes, bicycle frames, grilles", "trend": "+₹1 today"},
            {"id": "tin", "name": "Tin & Steel Cans (Pepa)", "rate": 22, "unit": "kg", "note": "Oil cans, ghee containers, food tins", "trend": "Stable"}
        ]
    },
    "ewaste": {
        "title": "E-Waste & Home Appliances",
        "icon": "💻",
        "items": [
            {"id": "split_ac", "name": "Split AC (1.5 Ton Full Set)", "rate": 4500, "unit": "piece", "note": "Indoor + Outdoor with copper coil", "trend": "Top Payout"},
            {"id": "window_ac", "name": "Window AC (1.5 Ton)", "rate": 3400, "unit": "piece", "note": "Copper compressor unit intact", "trend": "Top Payout"},
            {"id": "fridge", "name": "Refrigerator (Single / Double)", "rate": 1100, "unit": "piece", "note": "Complete with compressor & body", "trend": "High demand"},
            {"id": "washing_machine", "name": "Washing Machine", "rate": 950, "unit": "piece", "note": "Motor and drum intact", "trend": "Stable"},
            {"id": "laptop", "name": "Old / Broken Laptop", "rate": 400, "unit": "piece", "note": "Motherboard & body complete", "trend": "+₹50 bonus"},
            {"id": "cpu", "name": "Desktop Computer CPU", "rate": 280, "unit": "piece", "note": "With power supply and motherboard", "trend": "Stable"},
            {"id": "smartphone", "name": "Dead Smartphone / Tablet", "rate": 100, "unit": "piece", "note": "With internal logic board", "trend": "Instant cash"},
            {"id": "lead_battery", "name": "Inverter / Car Battery", "rate": 98, "unit": "kg", "note": "Lead acid UPS & car battery", "trend": "🔥 Top Value"}
        ]
    }
}
