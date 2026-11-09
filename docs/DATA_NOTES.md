# Data notes

Findings from inspecting the raw files in commit 02 (pinned revisions in `configs/default.yaml`,
hashes and row counts in `data/raw/MANIFEST.json`). Licenses: `docs/LICENSES.md`.

## Change from the PRD

The PRD's main knowledge base, `qgyd2021/e_commerce_customer_service`, is gone from the Hub
(checked 2026-11-09: the API returns "Repository Not Found", and the `qgyd2021` namespace
lists no datasets). Replacements, chosen with the author:

| PRD role | Now |
|---|---|
| Main knowledge base: FAQ | `NebulaByte/E-Commerce_FAQs` (Flipkart help-centre FAQs) |
| Main knowledge base: product info / model numbers | `InfiniFlow/Ecommerce-Customer-Service-Workflow` (6 Philips PDFs) |
| Extra FAQs | `MakTek/Customer_support_faqs_dataset` (unchanged) |
| Intent + colloquial phrasing | `bitext/Bitext-customer-support-llm-chatbot-training-dataset` (unchanged) |

Consequence: the product catalog is small (6 products). Commit 03 must decide whether that is
enough for 60 `model_number` eval questions or whether to add synthetic catalog entries.

## flipkart_faqs — `NebulaByte/E-Commerce_FAQs`

- One file, `FAQs.csv`, **659 rows**, one config, no splits. English.
- Columns: `parent_category`, `category_id`, `category`, `question_id`, `question`, `answer`,
  `faq_url`, `que_ans`.
- 34 categories. Largest: Flipkart Plus 50, Payment 43, SuperCoins 43, then four EV brands
  (Ather 42, Bounce 41, Ampere 40, BGauss 39). Core after-sales ones are small:
  Order 30, Cancellations and Returns 29, Shopping 22, Warranty 14, Refurbished 12, Shipping 7.
- `parent_category`: missing on 247 rows; others are Electric Vehicle (186, value has a
  trailing space), Others 82, Payment 62, Insurance 42, Flipkart Travel 31, Wallet 9.
- Quirks:
  - 2 empty answers (both Aegon Life Insurance). Drop.
  - 2 duplicate questions: one exact duplicate in Payment; "What is a convenience fee?" appears
    under both Flights and Hotels with different answers. 34 answers are reused across questions.
  - No HTML. Answers keep `\n` line breaks, leading/trailing newlines, and 94 `\xa0` (nbsp)
    characters. Some list items are glued together ("Net Banking Credit card EMIUPIWallets").
  - 210 answers name Flipkart; 29 mention rupees (₹ / Rs.); 6 contain URLs. Branded and
    India-specific; commit 03 should decide whether to neutralise the store name.
  - `que_ans` is `question + " " + answer` for 657 of 659 rows. Redundant; ignore it.
  - Answer length: median 208 chars, max 3518 ("Which products are not eligible for returns?").
- Many categories (EV brands, insurance, travel, loans) are off-topic for an after-sales bot.
  They are useful as **distractors** and as a source of plausible `no_answer` questions.

Field mapping: FAQ question ← `question`; FAQ answer ← `answer`; document/section ←
`category` (+ `parent_category`); citation id ← `question_id`.

## philips_manuals — `InfiniFlow/Ecommerce-Customer-Service-Workflow`

- Two zips, **6 PDFs**, all text-extractable with `pypdf` (no empty pages, ~99% ASCII).
- `product_infomation.zip` (sic): 3 short product leaflets, 2–3 pages each.
  Hair Dryer BHD308/10 (3000 Series, 1600W), BHD340/10 (3000 Series, 2100 W),
  BHD510/03 (5000 Series, 2300W). Feature bullets and specs.
- `user_guide.zip`: 3 full manuals. Air Fryer (26 pages), Headphones TAH6206 (13 pages),
  Monitor 24E1N2300A / 27E1N2300A (32 pages). Sections: safety, setup, cleaning,
  troubleshooting, warranty.
- Quirks:
  - The Air Fryer file is named `HD9650`, but the manual text says `HD928X`. Trust the text.
  - One leaflet filename lacks a hyphen (`Philips-Series-Hair-DryerBHD340.pdf`).
  - The monitor manual covers two models; the table of contents has dot leaders.
  - PDF text loses layout; tables (specs, food table) come out as run-on lines.

Field mapping: product name/model ← leaflet title line and model code (e.g. `BHD308/10`);
product attributes ← leaflet spec bullets; manual sections ← headings in the user guides.

## maktek_faqs — `MakTek/Customer_support_faqs_dataset`

- One file, `train_expanded.json`, **200 rows**, fields `question`, `answer`. English, ASCII.
- Quirk: despite the `.json` name, the file is **JSON Lines** (one object per line).
- Heavy duplication: 111 duplicate questions and 114 duplicate answers out of 200
  (the "expanded" file repeats pairs). Only ~89 unique questions. Dedupe in commit 03.
- Generic, synthetic, store-agnostic ("click 'Sign Up' on the top right corner of our
  website"). Answers are short (91–219 chars).

Field mapping: FAQ question ← `question`; FAQ answer ← `answer`.

## bitext — `bitext/Bitext-customer-support-llm-chatbot-training-dataset`

- One file, CSV, **26,872 rows**, no nulls. English, ASCII.
- Columns: `flags`, `instruction` (the user utterance), `category`, `intent`, `response`.
- 11 categories, **27 intents**, ~1000 rows each (950–1000).
  Intents: cancel_order, change_order, change_shipping_address, check_cancellation_fee,
  check_invoice, check_payment_methods, check_refund_policy, complaint,
  contact_customer_service, contact_human_agent, create_account, delete_account,
  delivery_options, delivery_period, edit_account, get_invoice, get_refund,
  newsletter_subscription, payment_issue, place_order, recover_password,
  registration_problems, review, set_up_shipping_address, switch_account, track_order,
  track_refund.
- `flags` are Bitext's linguistic-variation tags (394 combinations, e.g. `BL`, `BLQ`, `BLZ`).
  `Z` rows contain deliberate typos ("optionsx"); `Q` = colloquial. Useful for the
  `colloquial` eval group.
- Quirks:
  - Placeholders like `{{Order Number}}`, `{{Person Name}}`, `{{Refund Amount}}` in 6670
    utterances and 13006 responses. Fill or strip before use.
  - 2237 duplicate utterances (same text, usually same intent).
  - Responses are long, generic templates. Do **not** use them as knowledge.

Field mapping: utterance ← `instruction`; intent label ← `intent` (mapped to our 9 intents
in commit 09); variation tags ← `flags`.
