# TrustGate AI 🛡️
### AI-Assisted Brand Governance & Content Compliance Platform

TrustGate AI is a web-based brand governance platform that helps organisations review marketing content before publication. It checks submitted content against approved brand guidelines, verifies claims against stored brand facts, identifies potential visual inconsistencies and supports a human review and approval workflow.

The goal is to help content creators identify brand compliance issues early, reduce manual review effort and maintain consistent brand communication.

> **Project status:** Working prototype

---

## 🚀 Key Features

### 1. Role-Based Access
- Separate Admin, Creator and Reviewer roles.
- Role-based access to relevant application workflows.
- Login and authentication.

### 2. Brand Guidelines Management
- Import brand policy documents.
- Extract proposed brand facts from supported documents.
- Review, approve or reject proposed facts.
- Manage approved brand facts and terminology.
- Maintain prohibited phrases and brand rules.

### 3. Content Compliance Checking
- Submit content drafts for pre-publication review.
- Check claims against approved brand facts.
- Identify incorrect or conflicting promotional information.
- Detect prohibited terminology and phrases.
- Provide review findings and supporting evidence.
- Display suggested corrections for detected issues.

### 4. Visual Brand Compliance
- Register approved logos and artwork.
- Compare submitted images against approved visual references.
- Detect likely embedded logo matches using OpenCV.
- Identify similar or duplicate artwork using perceptual hashing.
- Display visual matching information to support review decisions.

### 5. Accessibility Checking
- Check supported HTML content for selected accessibility issues.
- Identify missing image alternative text.
- Detect certain explicit inline colour-contrast problems.
- Identify skipped heading levels.

### 6. Review and Approval Workflow
- Submit drafts for human review.
- Add reviewer comments and feedback.
- Revise and resubmit content.
- Maintain draft version history.
- Record review and approval decisions.

### 7. Insights and Audit
- View governance insights and analytics.
- Access built-in compliance benchmark testing.
- Track false-positive feedback.
- Review guideline clarity insights.
- Maintain an audit trail of important activities.
- Generate review reports and use browser printing to save them as PDF.

### 8. Optional Multi-Tenant Support
- Organisation-specific database storage.
- Organisation-specific visual asset directories.
- Hostname-based tenant selection.
- Organisation data isolation when correctly configured.

*Multi-tenant mode requires additional deployment configuration and is not enabled by default.*

---

## 🛠️ Technology Stack

| Component | Technology |
|---|---|
| Frontend | HTML, CSS, JavaScript |
| Backend | Python, FastAPI |
| Database | SQLite |
| Image Processing | OpenCV |
| Artwork Similarity | Perceptual Hashing |
| API Communication | HTTP / REST-style APIs |
| Application Server | Uvicorn |
| Testing | Pytest, JavaScript syntax checking |

Optional AI-assisted functionality requires the relevant external API configuration.

---

## 📁 Project Structure

```text
trustgate-ai/
│
├── backend/
│   ├── app.py
│   └── ...
│
├── frontend/
│   ├── app.js
│   ├── ...
│
├── demo_inputs/
│   ├── visual_assets/
│   ├── 01_solara_brand_policy.txt
│   ├── 02_bad_promo_draft.txt
│   ├── 03_clean_promo_draft.txt
│   ├── 04_tone_review_draft.txt
│   └── 05_accessibility_sample.html.txt
│
├── tests/
│
├── requirements.txt
├── .env.example
├── DEMO_GUIDE.md
└── README.md
```

*The exact files and folders may vary slightly depending on the project version.*

---

## ⚙️ Installation and Setup

### Prerequisites

Install the following before running the project:

- Python 3.10 or later (use the version supported by the project dependencies).
- pip
- Git
- A modern web browser.

### Step 1: Clone the Repository

```bash
git clone https://github.com/YOUR-USERNAME/trustgate-ai.git
```

Move into the project directory:

```bash
cd trustgate-ai
```

### Step 2: Create a Virtual Environment

```bash
python -m venv venv
```

Activate it on Windows:

```bash
venv\Scripts\activate
```

On macOS/Linux:

```bash
source venv/bin/activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

OpenCV is required for the visual logo-matching functionality.

### Step 4: Configure Environment Variables

If the project includes `.env.example`, create a local `.env` file using it as a starting point.

Configure optional AI API credentials only if you want to use the AI-assisted functionality.

**Important:** Never upload API keys, passwords, database files or other secrets to GitHub.

### Step 5: Start the Backend

Navigate to the backend folder:

```bash
cd backend
```

Start the application:

```bash
uvicorn app:app --reload
```

### Step 6: Open the Application

Open your browser and visit:

```text
http://127.0.0.1:8000
```

---

## 🧪 Demo Instructions

The project includes sample Solara brand data to demonstrate the main workflows.

1. Log in using an Admin account.
2. Import the sample Solara brand policy.
3. Review and approve the extracted brand facts.
4. Register the approved Solara logo and artwork.
5. Log in as a Creator.
6. Upload `02_bad_promo_draft.txt`.
7. Run the compliance check and inspect the findings.
8. Try `03_clean_promo_draft.txt` after confirming the approved facts.
9. Test the tone and accessibility examples.
10. Submit a draft for Reviewer approval.
11. Add reviewer comments and record the review decision.
12. Explore the insights and audit sections.

For detailed instructions and local demo credentials, refer to `DEMO_GUIDE.md`.

---

## 🔍 How It Works

```text
        ADMIN
          |
          v
   Import Brand Guidelines
          |
          v
   Review and Approve Facts
          |
          v
      SQLite Database
          |
          |
       CREATOR
          |
          v
    Submit Content Draft
          |
          v
    FastAPI Backend
          |
          v
   Compliance Checking
          |
     +----+-----+
     |          |
     v          v
 Fact Checks  Visual Checks
     |          |
     +----+-----+
          |
          v
   Review Findings
          |
          v
    HUMAN REVIEWER
          |
     +----+-----+
     |          |
     v          v
   Revision   Approval
     |          |
     +----------+
          |
          v
    Review History
```

---

## 🧪 Testing

The project has been tested using:

- Automated backend tests with Pytest.
- Frontend JavaScript syntax validation.
- Role-based login and access checks.
- Brand policy import and fact approval workflows.
- Content checking with incorrect and compliant sample drafts.
- Visual logo and artwork screening.
- Accessibility checks on supported HTML samples.
- Draft revision, reviewer comments and approval workflows.
- Tenant isolation tests for the optional multi-tenant implementation.

The previously tested project version recorded 131 passing automated tests.

To run the test suite:

```bash
pytest
```

To check frontend JavaScript syntax:

```bash
node --check frontend/app.js
```

---

## ⚠️ Known Limitations

- Automated findings are decision-support results, not guaranteed proof of brand violations.
- Visual matching may produce false positives or miss altered, rotated, transparent or very small logos.
- Accessibility checks cover selected source-level HTML patterns and are not a complete WCAG audit.
- AI-assisted functionality depends on external API configuration.
- Multi-tenant functionality requires explicit hostname and deployment configuration.
- The prototype has not been established as production-ready through large-scale performance or security testing.
- Human review is required for final approval.

---

## 🔮 Future Development

Planned improvements include:

- More accurate context-aware brand and claim verification.
- Improved logo and visual identity detection.
- More comprehensive WCAG accessibility checks.
- Support for additional document formats.
- Email and in-app review notifications.
- Integrations with content management and cloud storage platforms.
- Stronger organisation onboarding and administration.
- Advanced compliance analytics and trend reporting.
- Monitoring of published content through authorised platform integrations.

---

## 🔐 Security

This project is a prototype intended for development and demonstration.

Before production deployment:
- Replace demo credentials.
- Configure secure authentication and secret management.
- Use HTTPS.
- Secure uploaded files and database storage.
- Configure organisation isolation carefully.
- Perform security and access-control testing.

Do not use real confidential brand documents or sensitive business data in an unsecured demo deployment.

---

## 🎯 Project Objective

TrustGate AI aims to make brand governance proactive rather than reactive.

Instead of discovering brand inconsistencies after publication, teams can use TrustGate AI to review content before it goes live, understand potential issues, make corrections and obtain human approval.

**Review before you publish. Protect your brand at every step.**

---

## 👨‍💻 Project Information

**Project:** TrustGate AI  
**Category:** AI-Assisted Brand Governance  
**Type:** Web Application Prototype  
**Purpose:** Pre-publication brand compliance and content review

---

*Built as a prototype for the Inkloom AI brand-governance challenge.*
