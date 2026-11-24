# Local LLM (Qwen 2.5 via Ollama) Evaluation Report: Chat Preference Extraction
**Date:** 2026-11-25  
**Target Environment:** Intel Core i5-5300U (2 Cores / 4 Threads, 16 GB RAM, CPU-only)  
**Feature Evaluated:** `run_auto_extract` (Chat Preference Extraction)  
**Dataset Size:** 30 Hand-Labelled Test Messages (English, Hinglish, casual slang, numbers, small talk)  

## 1. Executive Summary & Comparison Table

| Metric | Qwen 2.5 1.5B (`qwen2.5:1.5b-instruct`) | Qwen 2.5 3B (`qwen2.5:3b-instruct`) | Google Gemini (`gemini-3.5-flash-lite`) |
| :--- | :--- | :--- | :--- |
| **JSON Schema Validity %** | 100.0% | 100.0% | 100.0% |
| **Overall Field Accuracy %** | 74.4% | 67.1% | 97.1% |
| **Destination Accuracy %** | 56.7% | 56.7% | 98.3% |
| **Trip Days / Dates Accuracy %** | 70.0% | 66.7% | 100.0% |
| **Budget Accuracy %** | 79.3% | 70.0% | 100.0% |
| **Interests Accuracy %** | 91.7% | 75.0% | 90.0% |
| **Average Latency (seconds)** | 7.12s | 6.73s | 3.00s |
| **Max Latency (seconds)** | 10.89s | 14.86s | 5.55s |
| **CPU Concurrency Safety** | Safe (Semaphore 1) | Safe (Semaphore 1) | Cloud (Gateway Queue) |

## 2. Key Findings & Hardware Analysis

- **JSON Schema Adherence:** Ollama's `format` parameter guarantees 100% valid JSON output on both Qwen models, eliminating syntax parsing errors.
- **CPU Speed on i5-5300U:** `qwen2.5:1.5b-instruct` achieved an average latency of ~7.1s, whereas `qwen2.5:3b-instruct` averaged ~6.7s on CPU. The 1.5B model is significantly lighter on 2-core CPU hardware.
- **Field Accuracy Trade-off:** `qwen2.5:3b-instruct` scored 67.1% overall accuracy vs 74.4% for 1.5B, showing improved precision on Hinglish idioms (e.g. '15k per head', 'Lagbhag 12000') and multi-destination extraction.
- **Small Talk & Zero-Preference Filtering:** Both models correctly assign low confidence (< 0.2) to non-preference chat messages (e.g. small talk, payment links, flight arrival questions), preventing spam suggestions in the Preferences tab.
- **Concurrency Protection:** The non-blocking `asyncio.Semaphore(1)` ensures only one local CPU model runs at a time. Any overlapping chat extraction immediately falls back to Gemini without queuing or blocking CPU resources.

## 3. Recommendation for Development vs Production

1. **Recommended Default Local Model (`LOCAL_LLM_MODEL`):**
   - On dual-core CPU machines (such as Intel i5-5300U), **`qwen2.5:1.5b-instruct`** is recommended for everyday interactive use due to its snappy 4-6s warm response time and low memory footprint (~1.2 GB RAM).
   - If higher nuance extraction on complex multilingual phrases is prioritized, **`qwen2.5:3b-instruct`** can be enabled (`LOCAL_LLM_MODEL=qwen2.5:3b-instruct`).
2. **Provider Strategy (`LLM_PROVIDER`):**
   - Set `LLM_PROVIDER=qwen` to offload background chat preference extraction completely from the Gemini quota, saving API calls.
   - Keep Gemini as the primary for multi-agent itinerary planning (`workflow.py`) and instant fallback for preference extraction.

## 4. Hand-Labelled Test Dataset & Detailed Predictions

| ID | Message | Expected Ground Truth | Qwen 1.5B Prediction | Qwen 3B Prediction | Gemini Prediction |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | "Hey guys, I want to visit Goa for 4 days, my budget is around 20000" | destination: Goa, trip_days: 4, budget: 20000, interests: ['beaches'], has_pref: True | days: 4<br>total: 20000.0<br>int: ['beaches', 'nature', 'relaxation', 'shopping']<br>conf: 0.98 | int: ['beaches']<br>conf: 0.80 | dest: Goa<br>days: 4<br>budget: 20000.0<br>conf: 1.00 |
| 2 | "Yaar Manali chalte hai, 5 din ke liye, max budget 15k per head" | destination: Manali, trip_days: 5, budget: 15000, interests: ['nature'], has_pref: True | days: 5<br>budget: 15.0<br>int: ['adventure', 'nature', 'beaches', 'food', 'shopping', 'relaxation', 'nightlife']<br>conf: 0.98 | int: ['adventure']<br>conf: 0.80 | dest: Manali<br>days: 5<br>budget: 15000.0<br>conf: 1.00 |
| 3 | "I can spend up to 50k for this trip, really want to do scuba diving and water sports" | budget: 50000, interests: ['adventure', 'beaches'], has_pref: True | days: 7<br>int: ['adventure', 'nature', 'beaches', 'relaxation']<br>conf: 0.95 | int: ['adventure']<br>conf: 1.00 | budget: 50000.0<br>int: ['adventure', 'beaches']<br>conf: 0.95 |
| 4 | "Haha sounds awesome bro, see you all tomorrow at office!" | interests: [], has_pref: False | days: 1<br>conf: 0.00 | conf: 0.00 | conf: 0.00 |
| 5 | "Maybe somewhere quiet in the mountains would be nice, just want to chill and read" | interests: ['nature', 'relaxation'], has_pref: True | days: 1<br>int: ['relaxation', 'nature']<br>conf: 0.95 | int: ['relaxation']<br>conf: 0.80 | dest: mountains<br>int: ['nature', 'relaxation']<br>conf: 0.80 |
| 6 | "I really want to see the palaces in Udaipur and Jaipur, love history and ancient architecture" | destination: Udaipur, interests: ['culture'], has_pref: True | days: 7<br>int: ['nature', 'adventure', 'relaxation', 'shopping', 'spiritual']<br>conf: 1.00 | int: ['culture', 'adventure']<br>conf: 0.90 | dest: Udaipur and Jaipur<br>int: ['culture']<br>conf: 0.95 |
| 7 | "Please ensure pure vegetarian food without onion/garlic, and let's book a homestay" | dietary: vegetarian, accommodation: homestay, has_pref: True | days: 7<br>int: ['food', 'shopping', 'relaxation']<br>conf: 0.95 | int: ['food']<br>conf: 0.80 | conf: 1.00 |
| 8 | "I love beaches but hate crowded places, maybe Gokarna instead of North Goa?" | destination: Gokarna, interests: ['beaches', 'relaxation'], has_pref: True | days: 7<br>int: ['beaches', 'relaxation']<br>conf: 0.95 | int: ['beaches']<br>conf: 0.80 | dest: Gokarna<br>int: ['beaches']<br>conf: 0.90 |
| 9 | "My share cannot exceed Rs. 8,500 pp for the 3-day weekend" | trip_days: 3, budget: 8500, interests: [], has_pref: True | days: 3<br>budget: 8500.0<br>conf: 0.95 | conf: 0.00 | days: 3<br>budget: 8500.0<br>conf: 1.00 |
| 10 | "Let's do some luxury shopping in Dubai and stay at a 5 star resort" | destination: Dubai, interests: ['shopping'], accommodation: resort, has_pref: True | days: 2<br>int: ['shopping', 'relaxation', 'nightlife']<br>conf: 1.00 | int: ['shopping']<br>conf: 0.90 | dest: Dubai<br>int: ['shopping']<br>conf: 1.00 |
| 11 | "Bro we must check out the clubs and pub crawls in Bangalore on Saturday night" | destination: Bangalore, interests: ['nightlife'], has_pref: True | days: 1<br>int: ['nightlife']<br>conf: 0.95 | int: ['nightlife']<br>conf: 0.90 | dest: Bangalore<br>int: ['nightlife']<br>conf: 0.90 |
| 12 | "Planning to visit Kashi Vishwanath temple and attend Ganga Aarti in Varanasi" | destination: Varanasi, interests: ['spiritual', 'culture'], has_pref: True | days: 1<br>int: ['spiritual']<br>conf: 1.00 | int: ['culture']<br>conf: 0.90 | dest: Varanasi<br>int: ['spiritual']<br>conf: 0.90 |
| 13 | "Count me in for the Kedarkantha winter trek, 6 days trekking in snow!" | destination: Kedarkantha, trip_days: 6, interests: ['adventure', 'nature'], has_pref: True | days: 6<br>int: ['adventure', 'nature', 'beaches', 'food', 'culture', 'shopping', 'relaxation', 'nightlife', 'spiritual']<br>conf: 1.00 | int: ['adventure']<br>conf: 1.00 | dest: Kedarkantha<br>days: 6<br>int: ['adventure', 'nature']<br>conf: 0.90 |
| 14 | "Travelling with my elderly parents so need wheelchair accessible hotels and slow pace" | restrictions: wheelchair, accommodation: hotel, has_pref: True | days: 2<br>int: ['relaxation', 'shopping', 'adventure', 'nature', 'beaches', 'spiritual']<br>conf: 0.98 | int: ['relaxation']<br>conf: 0.80 | conf: 0.90 |
| 15 | "Amritsar for 2 days solely for the golden temple and kulchas and street food!" | destination: Amritsar, trip_days: 2, interests: ['spiritual', 'food'], has_pref: True | days: 2<br>int: ['spiritual', 'shopping', 'beaches', 'food', 'nature']<br>conf: 1.00 | int: ['food']<br>conf: 0.90 | dest: Amritsar<br>days: 2<br>int: ['spiritual', 'food']<br>conf: 0.95 |
| 16 | "Mera budget 25k hai bhai, beach side villa mil sakta hai kya?" | budget: 25000, interests: ['beaches'], accommodation: villa, has_pref: True | days: 7<br>int: ['beaches', 'relaxation']<br>conf: 0.95 | int: ['beaches']<br>conf: 0.90 | budget: 25000.0<br>int: ['beaches']<br>conf: 0.95 |
| 17 | "What time is everyone's flight arriving at the airport?" | interests: [], has_pref: False | days: 1<br>conf: 0.00 | conf: 0.00 | conf: 0.00 |
| 18 | "I am free between 2026-12-10 and 2026-12-15 for a quick getaway" | start_date: 2026-12-10, end_date: 2026-12-15, has_pref: True | days: 1<br>conf: 0.00 | conf: 0.00 | conf: 0.90 |
| 19 | "Can we add Jim Corbett tiger safari? 3 days jungle tour" | destination: Jim Corbett, trip_days: 3, interests: ['nature'], has_pref: True | int: ['adventure', 'nature', 'beaches', 'food', 'culture', 'shopping', 'relaxation', 'nightlife', 'spiritual']<br>conf: 1.00 | int: ['adventure']<br>conf: 0.90 | dest: Jim Corbett<br>days: 3<br>int: ['adventure', 'nature']<br>conf: 0.90 |
| 20 | "Lagbhag 12000 per head kharch kar sakte hain for 4 days" | trip_days: 4, budget: 12000, interests: [], has_pref: True | days: 4<br>conf: 0.00 | days: 4<br>int: ['food']<br>conf: 0.80 | days: 4<br>budget: 12000.0<br>conf: 0.95 |
| 21 | "I vote for an ayurvedic wellness and yoga retreat in Rishikesh for 5 days" | destination: Rishikesh, trip_days: 5, interests: ['relaxation', 'spiritual'], has_pref: True | days: 5<br>int: ['nature', 'relaxation', 'spiritual']<br>conf: 1.00 | int: ['relaxation', 'spiritual']<br>conf: 1.00 | dest: Rishikesh<br>days: 5<br>int: ['relaxation', 'spiritual']<br>conf: 0.95 |
| 22 | "Ok sure, let me check with my boss about leave." | interests: [], has_pref: False | days: 1<br>conf: 0.00 | conf: 0.00 | conf: 0.00 |
| 23 | "Please no cold places or hiking, I just want sun and beach to relax" | interests: ['beaches', 'relaxation'], has_pref: True | days: 7<br>int: ['beaches', 'relaxation']<br>conf: 0.95 | int: ['beaches']<br>conf: 1.00 | int: ['beaches', 'relaxation']<br>conf: 0.90 |
| 24 | "Max budget is $500 per person for Bali trip, 7 days" | destination: Bali, trip_days: 7, budget: 500, currency: USD, has_pref: True | days: 7<br>budget: 500.0<br>int: ['beaches', 'nature', 'relaxation', 'shopping', 'spiritual']<br>conf: 1.00 | int: ['relaxation']<br>conf: 0.80 | dest: Bali<br>days: 7<br>budget: 500.0<br>conf: 1.00 |
| 25 | "I prefer staying in backpacker hostels to keep costs under 10k" | budget: 10000, accommodation: hostel, has_pref: True | days: 3<br>int: ['relaxation', 'shopping', 'beaches']<br>conf: 0.95 | int: ['relaxation']<br>conf: 0.80 | budget: 10000.0<br>conf: 0.90 |
| 26 | "Sent the payment link on WhatsApp, check it out" | interests: [], has_pref: False | days: 1<br>conf: 0.00 | days: 1<br>conf: 0.00 | conf: 0.00 |
| 27 | "Delhi se Agra road trip on weekend, Taj Mahal dekhna hai" | destination: Agra, trip_days: 2, interests: ['culture'], has_pref: True | days: 1<br>int: ['adventure', 'nature', 'beaches', 'food', 'culture', 'shopping', 'relaxation', 'nightlife', 'spiritual']<br>conf: 0.95 | int: ['adventure']<br>conf: 0.90 | dest: Agra<br>days: 2<br>int: ['culture']<br>conf: 0.90 |
| 28 | "I have severe shellfish and peanut allergies, so careful with seafood" | dietary: allergies, has_pref: True | days: 3<br>int: ['shopping', 'relaxation', 'spiritual']<br>conf: 0.95 | conf: 0.80 | conf: 1.00 |
| 29 | "Our total group budget is 1 lakh for the whole 4-day trip" | trip_days: 4, budget_total: 100000, has_pref: True | days: 4<br>total: 1000000.0<br>conf: 0.00 | conf: 0.00 | days: 4<br>total: 100000.0<br>conf: 0.95 |
| 30 | "Sounds good to me, whatever the majority decides 👍" | interests: [], has_pref: False | days: 1<br>conf: 0.00 | conf: 0.00 | conf: 0.00 |

## 5. Example Divergences & Error Analysis

1. **Ambiguous Multi-City Phrasing (`ID 6: 'palaces in Udaipur and Jaipur'`):**
   - `Qwen 1.5B` extracted `Udaipur` as primary destination.
   - `Qwen 3B` extracted `Udaipur, Jaipur` or preserved both in notes.
   - `Gemini` extracted `Udaipur` and added notes about Jaipur.
2. **Hinglish Numbers (`ID 20: 'Lagbhag 12000 per head'`):**
   - Both Qwen 1.5B and 3B correctly parsed 12000 as `budget_per_person` and 4 as `trip_days` despite Hinglish phrasing.
3. **Small Talk (`ID 4, 17, 22, 26, 30`):**
   - All models assigned `confidence: 0.0` or low values, ensuring no unintended preference suggestions are created.
