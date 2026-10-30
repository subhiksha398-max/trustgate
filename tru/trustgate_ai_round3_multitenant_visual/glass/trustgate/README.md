# TrustGate AI - Round 2 prototype
Stack (as in the deck): HTML/CSS/JavaScript, FastAPI, SQLite, python-docx, pypdf, Pillow, pytest, plus Claude (Anthropic API) for the AI layer. FastAPI is served by uvicorn.

## Run
    pip install -r requirements.txt
    cd backend && uvicorn app:app --reload      # open http://127.0.0.1:8000
    pytest tests                                 # from project root

## Try the deck's example
1. Sign in as Creator (see demo accounts below), choose New draft, paste: `SOLARA FLAT 50% OFF. LIFETIME WARRANTY`
2. See two findings with source and suggested fix. Resubmit with the fixes applied.
3. Switch to Reviewer: mark each finding as correct or a false alarm, then approve or return (comment required if findings remain). Run the labelled benchmark from Insights and check the guideline clarity table.
4. Switch to Admin: upload a DOCX, PDF or TXT policy from Brand facts, review/edit/reject its proposals, and explicitly approve each new fact or update a suggested match. Edit approved facts and inspect their version history there.

Data lives in backend/trustgate.db.

## What can be checked
| Upload | How it is read | Needs AI key? |
|---|---|---|
| Pasted text, TXT, DOCX | Read directly | No |
| PDF | Selectable text is extracted page by page (first 100 pages). A scanned PDF has no text: export its pages as PNG or JPG | No |
| PNG, JPG | Bounded dimension and sampled brand-colour checks run. Optional Claude vision returns image text for review against the same approved facts | Only to read the words |

Uploads are limited to 10 MB. If an image's words could not be read (AI off or the call failed), the draft gets a "Needs human review" finding, **Image text not read**, so a poster never passes silently.

Image checks accept PNG/JPEG data based on its file signature, not just its extension. Decoding is limited to 12 million pixels and an 8,000-pixel maximum side; images below 600x315 px are flagged. Brand-colour comparison quantizes a 64x64 sample to five colours and compares the most frequent sampled RGB value with approved `#RRGGBB` facts using Euclidean RGB distance. Distance `<= 90` is the approximate match tolerance. This is a coarse palette check, not a full-image compliance result. Admins can add approved visual reference images from Brand facts. The image checker computes a perceptual hash and reports a near-duplicate whole-image match when appropriate. This is useful for spotting re-uploads or near-identical approved artwork, but it does **not** reliably detect whether a logo is embedded correctly inside a different poster. Text-size/readability analysis is not a complete visual accessibility audit. Vision-derived claim findings require a reviewer to confirm the transcription against the original image. Draft image uploads are not retained, so users must keep the original file available for that review.

## Rules without AI
The rules understand common phrasings, so the core works with no API key:
- Discounts: `50% off`, `fifty percent off`, `twenty-five per cent off`, `half price`, `half off`, `a third off`, `a quarter off`. A figure that differs from the approved offer is auto-fixable (for example "half price" becomes "15% off").
- Multi-buy deals (`buy one get one free`, `BOGO`, `2 for 1`) have no approved record, so they are flagged for review.
- Warranty: `1-year warranty`, `twelve month guarantee`, `warranty of 5 years`, `lifetime warranty`, `warranty for life`, `warranty that lasts forever`, `warranty never expires`. "Protection / coverage / replacements for life" are flagged for review but never auto-rewritten.

## Upgrade notes (Round 2.1)

The checker now includes conservative accessibility screening when pasted content contains HTML:
- Flags images without an `alt` attribute; empty alt text is a human-review prompt because it can be correct for decorative images.
- Calculates WCAG AA normal-text contrast for explicit inline `color` and `background-color` pairs, and flags ratios below 4.5:1 for review. It does not infer external/computed CSS or large-text status.
- Flags skipped heading levels as a review prompt.
- Surfaces selected subjective promotional superlatives as human-review prompts, never as proof that a claim is false.

These are source-level screening checks, not a full accessibility audit. Rendered layouts, external stylesheets, keyboard operation, screen-reader output and image meaning still require validation. Findings are deliberately review-only where context is needed.

For HTTPS deployments, set `TRUSTGATE_COOKIE_SECURE=1` so the session cookie is sent only over secure connections. Do not set this when running locally over plain HTTP. Demo accounts are for local demos only and must be removed/changed before deployment.

## AI layer (optional, uses Claude)
Rules are exact but only match patterns. The AI layer reads the copy like a human reviewer and catches what the rules miss, for example "cheapest deal ever" or "nobody beats our quality", and it reads the text inside images. Long documents are sent in pieces (up to 5 x 8,000 characters); beyond that the rules still cover everything and the audit trail notes that AI review was partial.

    # Windows PowerShell
    $env:ANTHROPIC_API_KEY = "sk-ant-..."
    # macOS / Linux
    export ANTHROPIC_API_KEY="sk-ant-..."
    cd backend && uvicorn app:app --reload

The header badge shows "AI on" when enabled. Optional: set `ANTHROPIC_MODEL` to change the model (default `claude-sonnet-5-5`).

What the AI does:
1. **Reads image text and finds missed claims.** Extra findings are tagged "AI-detected" and always marked "Needs human review". They are never auto-fixed.
2. **Suggests a rewrite.** On a draft, the Creator can click "Suggest a rewrite with AI". The result fills the revise box; the Creator edits and resubmits.

Safety design:
- The deterministic rules stay the judge; the AI only adds review-only flags.
- A finding whose quoted phrase is not in the text is discarded, so the model cannot invent problems.
- The AI only sees the approved facts and the draft text; copy is treated as untrusted data (prompt-injection guard).
- If the AI is off or fails, checking continues with rules only, and the failure is written to the audit trail.

Try it: `Grab it at half price and enjoy protection for life.` The rules alone flag both phrases. With AI on, `Our cheapest deal ever, and nobody beats our quality.` is also flagged, and a poster image saying "Half price. Warranty for life." is read and checked.

## Measured accuracy and reviewer feedback
`backend/benchmark.py` contains the versioned fictional benchmark dataset (v1.1.0, 140 drafts). It covers correct and incorrect discounts/prices, expired offers, warranty mismatches, unsupported and ambiguous claims, terminology violations, paraphrases, and harmless copy. Labels are authored in the fixture, validated before scoring, and never inferred from checker predictions. Each draft has an expected result and, when applicable, an expected issue category and classification.

Run the deterministic benchmark from the project root:

    python backend/benchmark.py

To also evaluate the optional Claude-assisted configuration on the same fictional fixtures:

    python backend/benchmark.py --with-ai

The AI command makes external model calls and may incur API cost. It sends only the fictional benchmark drafts and fictional facts in the checked-in fixture, not user drafts or database contents. If Claude is unavailable, the JSON output says `configuration.ai: unavailable` and omits AI metrics. The Reviewer/Admin **Run benchmark** action uses this same evaluator and stores its dataset version, example count, configuration and metrics.

Claim/finding-event precision, recall and F1 use category-matched findings: precision = TP/(TP+FP), recall = TP/(TP+FN), F1 = 2PR/(P+R). Classification accuracy is scored separately on category-matched findings, so finding the claim but assigning the wrong classification remains a classification error. Draft-level binary metrics measure whether any finding was expected versus whether any finding was raised; this is a different task from category-matched finding detection. False positives, false negatives and classification errors are also reported by issue category. Zero denominators safely produce 0 for precision, recall, F1 and classification accuracy. These fixture-specific measurements are not production accuracy guarantees. Reviewer marks are stored per reviewer, draft version and finding. The guideline clarity table groups the latest mark from each reviewer and reports false-alarm share by source and finding type. A reviewer can change their mark later without creating duplicate votes.

## Policy-to-facts ingestion
Admins can import DOCX, PDF or TXT policies from Brand facts. Deterministic extraction proposes explicit discounts and validity dates, warranty periods, prices, and quoted banned phrases. If AI is configured, Admins can opt into additional candidates. AI output is accepted only when its kind/value is valid and its quoted evidence appears verbatim in the extracted text. If AI extraction fails, deterministic proposals remain available.

Every proposal is pending until an Admin edits, rejects, approves it as a new fact, or explicitly updates a suggested existing fact. Pending and rejected proposals are never passed to the checker. Approved policy-backed facts retain the exact source passage and filename; uploaded files themselves are not retained. Findings snapshot the fact ID/version and passage used when checked, so later fact edits do not rewrite older evidence. Direct fact edits and removals are audited and appear in Admin fact history. Legacy facts receive a starting history snapshot during migration.

## Login and roles
Every screen and API call requires sign-in. On the login page you choose a role, then enter a username and password. The server checks that the account really has that role.

| Role | Username | Password | Can do |
|---|---|---|---|
| Creator | `asha` | `Creator@123` | Create, revise and resubmit their own drafts; comment on them |
| Reviewer | `ravi` | `Reviewer@123` | See all drafts, approve or return, Insights, Audit trail |
| Admin | `meena` | `Admin@123` | Manage brand facts, view drafts, Insights, Audit trail |

"Use the demo account" on the login page signs in with these in one click. To switch roles during a demo, choose Sign out, pick another role, and sign in.

How it works:
- Passwords are stored as salted PBKDF2-SHA256 hashes, never as plain text.
- A successful sign-in creates a random session token held in an HttpOnly, SameSite=Lax cookie (8 hours). Only a hash of the token is stored on the server.
- The role always comes from the server-side account. A browser cannot claim a role by editing headers.
- Creators can only open and comment on their own drafts.
- 5 failed attempts for a username lock it for 60 seconds. Wrong password and unknown user show the same message.
- Sign-ins, failed sign-ins and sign-outs are written to the audit trail.

Before any real use: change or remove the demo accounts and the `DEMO` block in `frontend/app.js`, serve over HTTPS and add the `secure` flag to the cookie in `backend/app.py`, and add a way to create and reset users.


## Upgrade notes (Round 2.2)

### Tone and terminology
- Added review-only heuristics for high-pressure sales language, selected subjective superlatives, and long all-caps text.
- These are prompts for human review, not evidence that a claim is false. To reduce duplicate alerts, the tone heuristic skips a sentence that already has a finding and avoids generic tone flags in offer/price sentences.
- Existing approved `tone`, `term`, and `banned` facts remain the deterministic source of truth for configured brand vocabulary.

### Visual references
- Admins can add or remove approved PNG/JPG visual references in **Brand facts**.
- Uploaded draft images are compared to reference images using a 64-bit difference hash. A near-duplicate match is a useful signal for repeated/near-identical artwork, not proof of logo correctness. A different poster that contains the correct logo will not necessarily match the reference image.
- Reference files are stored in `backend/approved_visual_assets` by default. Set `TRUSTGATE_ASSET_DIR` to a protected, persistent directory in deployments.

### Review reports
- Each draft has a **Review report / Save PDF** action. It opens a printable HTML report containing the content, decision metadata, findings, suggested corrections, source evidence, and comments. Use the browser's Print dialog and select **Save as PDF**.
- The report explicitly states that reviewer approval is not the same as publication.
- An optional generic publishing webhook is available for a receiving CMS/automation adapter. It is disabled unless both `TRUSTGATE_PUBLISH_WEBHOOK_URL` and `TRUSTGATE_PUBLISH_WEBHOOK_TOKEN` are configured. The destination must use HTTPS unless `TRUSTGATE_ALLOW_INSECURE_WEBHOOK=1` is deliberately enabled for local testing. The request includes a bearer token and `X-TrustGate-Signature: sha256=...` HMAC header. Only a reviewer-approved current version can be sent, and duplicate sends of the same version are blocked. A successful webhook response means the receiver accepted the event; it does not prove that the destination actually published the content.

### Security and deployment
- Every response now includes basic browser security headers. HTTPS deployments should set `TRUSTGATE_COOKIE_SECURE=1`.
- `TRUSTGATE_PRODUCTION=1` requires `TRUSTGATE_COOKIE_SECURE=1`, removes built-in demo accounts during startup, and disables public self-registration. Create accounts through a trusted deployment process using `python backend/create_user.py --username admin@example.com --name "Admin Name" --role admin` (set `TRUSTGATE_DB` to the intended database first). The script prompts for the password rather than accepting it on the command line.
- Set `TRUSTGATE_DB` and `TRUSTGATE_ASSET_DIR` to protected, persistent paths and keep them backed up. Never expose SQLite files, asset directories, logs, or environment secrets through the web server.
- The initial build was single-organisation. The current Round 3 build adds opt-in host-routed, database-per-tenant isolation; see the Round 3 section below for required configuration and deployment caveats.
- Before real production use, perform a deployment-specific security review, configure HTTPS/reverse-proxy host restrictions, define retention/deletion policies, and review any content sent to external AI providers.

### New automated coverage
- Added tests for tone-review prompts, printable report generation, visual-reference access controls and duplicate screening, and browser security headers.
- At Round 2.2, 128 tests passed. The current Round 3 suite has 131 passing tests in the development environment. Benchmark numbers remain tied to the versioned fictional dataset and are not a production-accuracy guarantee.


## Upgrade notes (Round 3: tenant isolation and embedded logo screening)

### Organisation-aware isolation (database-per-tenant)
This build adds an opt-in host-routed multi-tenant mode. Set `TRUSTGATE_MULTI_TENANT=1` and configure `TRUSTGATE_ORG_HOSTS` as a JSON object mapping each exact organisation hostname to a unique slug, for example:

```env
TRUSTGATE_MULTI_TENANT=1
TRUSTGATE_ORG_HOSTS={"acme.example.com":"acme","northwind.example.com":"northwind"}
TRUSTGATE_TENANT_DB_DIR=./private-data/tenant-databases
TRUSTGATE_ASSET_DIR=./private-data/approved_visual_assets
```

Each mapped hostname uses its own SQLite database and its own approved-asset subdirectory. Facts, users, sessions, drafts, policy proposals, comments, feedback, audits, benchmark runs, visual references and publication events are isolated because they live in the tenant's database. Unmapped hosts receive HTTP 421. Tenant slugs are validated before constructing file paths. Each tenant database is initialized on first request. In development mode, each fresh tenant database gets its own demo accounts; production mode removes demo accounts and does not create them. Use `python backend/create_user.py` with `TRUSTGATE_DB` set to the intended tenant database to provision production users.

**Deployment requirements:** this is host-routed isolation, not a substitute for infrastructure controls. Terminate TLS for each configured host, restrict accepted Host headers at the reverse proxy, do not trust arbitrary forwarded-host headers, protect the tenant database and asset directories, and back them up separately. Use a distinct database path and asset parent directory per deployment. Do not enable multi-tenant mode without a valid host map. Test host routing behind the actual reverse proxy before production.

### Embedded logo screening
Approved visual references now have a type: `logo` or `artwork`. Upload a tightly cropped logo using **Logo (embedded matching)**. With OpenCV installed, TrustGate searches the submitted image at multiple scales using normalized template matching and reports a likely match score and bounding box. High scores are marked as likely matches, middling scores require review, and low scores warn that no confident match was found. This is only a screening signal: compression, transparent backgrounds, rotation, colour changes, skew, occlusion, and very small logos can reduce accuracy; repeated patterns can create false positives. Human review remains required. Use **Artwork (whole-image matching)** for duplicate/near-duplicate campaign-artwork screening.

### New configuration dependencies and tests
`opencv-python-headless` is included for local template matching. If OpenCV is unavailable, the app reports the logo check as unavailable rather than treating it as passed. The tests cover tenant data and asset isolation across two hostnames, rejection of unmapped hosts, and logo matching inside a different poster. The complete test suite currently has 131 passing tests in the development environment.
