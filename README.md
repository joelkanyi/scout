# Scout

**Automated Job Application Platform** — scrape jobs, AI-score them against your resume, get tailored CVs, and auto-apply. Runs locally on your machine. Works for any profession.

Scout finds jobs from 15+ sources, scores them against your profile using AI, tailors your resume for each application, and can auto-fill application forms. Everything runs locally — your data never leaves your machine.

---

## What You Need

**A Mac or Linux machine** and **one of these AI providers** (choose during setup):

| Provider | Cost | How to get it |
|----------|------|---------------|
| Google Gemini | **Free** | [Get API key](https://aistudio.google.com/app/apikey) (takes 30 seconds) |
| Ollama | **Free** | [Download](https://ollama.com/download), then run `ollama pull llama3.2` |
| Anthropic Claude | ~$5/month | [Get API key](https://console.anthropic.com/settings/keys) |
| OpenAI-compatible | Varies | Any OpenAI-style API: Alibaba **Qwen/DashScope**, DeepSeek, OpenAI, Groq. Enter the base URL, key, and model in `scout setup`. |

**For PDF resume export**, install Pango (the DOCX export works without it):

- macOS: `brew install pango`
- Debian/Ubuntu: `sudo apt-get install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0`

---

## Quick Install

```bash
curl -fsSL --retry 5 --retry-all-errors https://raw.githubusercontent.com/joelkanyi/scout/main/install.sh | bash
```

This installs Python 3.12+, Node.js, all dependencies, and the `scout` command. Takes about 3 minutes.

After install, open a new terminal (or `source ~/.zshrc`) and run:

```bash
scout setup
```

The setup wizard walks you through everything. If you prefer manual setup, keep reading.

---

## Manual Setup

### Step 1: Clone and install

```bash
git clone https://github.com/joelkanyi/scout.git
cd scout

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install Scout
pip install -e .

# Install Chromium for auto-apply (optional)
playwright install chromium

# Build the web dashboard
cd ui && npm install && npm run build && cd ..
```

### Step 2: Configure your AI provider

Copy the example environment file and edit it:

```bash
cp .env.example .env
```

Open `.env` and set your AI provider. Pick one:

**Option A — Google Gemini (free):**
```env
AI_PROVIDER=gemini
AI_API_KEY=your-gemini-api-key-here
AI_MODEL=gemini-2.0-flash
```

**Option B — Ollama (free, local):**
```env
AI_PROVIDER=ollama
AI_MODEL=llama3.2
```
Make sure Ollama is running: `ollama serve` (in a separate terminal).

**Option C — Anthropic Claude (paid, best quality):**
```env
AI_PROVIDER=anthropic
AI_API_KEY=sk-ant-your-key-here
AI_MODEL=claude-haiku-4-5-20251001
```

### Step 3: Set up your master resume

Your master resume is the source of truth. Scout uses it to tailor resumes for each job. Copy the example and fill in your info:

```bash
cp resume/master.json.example resume/master.json
```

Open `resume/master.json` in any text editor and fill in your details. Here's the structure:

```json
{
  "personal": {
    "name": "Jane Smith",
    "email": "jane@example.com",
    "phone": "+1 555 123 4567",
    "location": "London, UK",
    "linkedin": "https://linkedin.com/in/janesmith",
    "github": "",
    "website": ""
  },
  "summary": "Registered Nurse with 8 years of critical care experience in ICU and Emergency departments. Specialized in patient assessment, ventilator management, and care coordination. PALS and ACLS certified.",
  "experience": [
    {
      "role": "Senior ICU Nurse",
      "company": "City Hospital",
      "location": "London, UK",
      "start_date": "2020-03",
      "end_date": "present",
      "bullets": [
        {
          "text": "Managed care for 4-6 critically ill patients per shift in a 20-bed ICU unit",
          "tags": ["Critical Care", "Patient Management"]
        },
        {
          "text": "Trained 12 new graduate nurses in ventilator management and patient assessment protocols",
          "tags": ["Training", "Mentorship"]
        }
      ]
    }
  ],
  "skills": [
    "Critical Care",
    "Patient Assessment",
    "PALS",
    "ACLS",
    "BLS",
    "EHR Systems",
    "Ventilator Management",
    "Medication Administration"
  ],
  "education": [
    {
      "degree": "BSc Nursing",
      "institution": "University of London",
      "year": "2016"
    }
  ],
  "projects": [],
  "certifications": [
    "Registered Nurse (NMC)",
    "PALS Certified",
    "ACLS Certified"
  ],
  "languages": ["English", "French"]
}
```

**Tips for your master resume:**
- Put ALL your experience, not just the highlights. Scout picks the most relevant parts for each job.
- Each bullet should describe what you did and (if possible) quantify the impact.
- The `tags` field helps Scout match bullets to job requirements. Use skill names from your field.
- Include ALL certifications — Scout will never fabricate certifications that aren't in your master resume.
- You can always update this later with `scout profile` or by editing the file directly.

### Step 4: Set your job preferences

Run the interactive preferences wizard:

```bash
scout profile
```

This asks you:
1. **What field are you in?** (Technology, Healthcare, Hospitality, Education, or General)
2. **Job titles** — what roles you're looking for (e.g., "Registered Nurse, ICU Nurse" or "Software Engineer, Backend Developer")
3. **Locations** — where you want to work (e.g., "London, Remote, New York")
4. **Experience level** — junior, mid, senior, staff, or lead
5. **Remote preference** — remote first, hybrid, on-site, or any
6. **Required keywords** — jobs must mention at least one of these (e.g., "nursing, ICU" or "Python, React")
7. **Excluded keywords** — reject jobs containing these (e.g., "unpaid, sales")
8. **Minimum salary** and **minimum match score**

Your preferences are saved to `config/preferences.yaml`. You can edit this file directly or re-run `scout profile` anytime.

### Step 5: Verify your setup

```bash
scout doctor
```

This checks everything: Python version, AI provider, database, resume, preferences, Chromium, and dashboard. Fix anything it flags before continuing.

---

## Usage

### Find jobs

```bash
scout scrape
```

This scrapes 15+ job sources (Indeed, LinkedIn, Arbeitnow, RemoteOK, Remotive, SmartRecruiters, Greenhouse, TheMuse, and more). Tech-specific sources like AndroidJobs and HackerNews only run if your job titles are in technology.

### Score jobs with AI

```bash
scout score
```

This sends each unscored job to your AI provider to get a match score (0-100%) based on your resume and preferences. Jobs above your threshold go to the apply queue.

To score just a few to test:

```bash
scout score --limit 5
```

### View your jobs

**In the terminal:**
```bash
scout jobs                    # List all jobs
scout jobs --status scored    # Only scored jobs
scout jobs --source indeed    # Only from Indeed
scout status                  # Today's stats
```

**In the web dashboard:**
```bash
scout ui
```

This opens a dashboard at http://localhost:8000 with:
- Job pipeline (Kanban board)
- Analytics and charts
- Resume editor
- Settings management

### Build a tailored resume

```bash
scout resume <job-id>
```

This generates a PDF and DOCX resume tailored to the specific job, plus a cover letter. The job ID is shown in `scout jobs` output (first 12 characters are enough).

### Apply to jobs

**Preview first (dry run):**
```bash
scout apply --dry-run
```

This fills out application forms without submitting, so you can verify everything looks right.

**Submit for real:**
```bash
scout apply --run
```

Currently supports Greenhouse, Lever, and Workday application portals. LinkedIn Easy Apply is not supported.

**Important:** For healthcare and education roles, auto-apply is disabled. These regulated professions require you to manually verify credential requirements for each application.

### Run on autopilot

```bash
scout daemon start
```

This runs scraping (every 6 hours), scoring (every 6 hours), email sync (every 2 hours), and ghosted detection (daily) in the background.

Stop it with:
```bash
scout daemon stop
```

---

## All Commands

| Command | What it does |
|---------|-------------|
| `scout setup` | First-run setup wizard |
| `scout scrape` | Scrape jobs from all sources |
| `scout score` | AI-score unscored jobs |
| `scout score --limit 10` | Score only 10 jobs |
| `scout jobs` | List scraped jobs |
| `scout jobs --status apply_queue` | Show jobs ready to apply |
| `scout status` | Today's stats summary |
| `scout resume <job-id>` | Build tailored resume for a job |
| `scout apply --dry-run` | Preview applications without submitting |
| `scout apply --run` | Submit applications for real |
| `scout ui` | Open web dashboard |
| `scout ui --dev` | Dashboard with hot-reload (for development) |
| `scout profile` | Change job search preferences |
| `scout doctor` | Check if everything's working |
| `scout update` | Pull latest code and reinstall |
| `scout dedup` | Find and remove duplicate jobs |
| `scout dedup --merge` | Actually merge duplicates |
| `scout email-sync` | Scan Gmail for application status emails |
| `scout ghosted` | Flag applications with no reply in 21 days |
| `scout auth gmail` | Connect Gmail (one-time OAuth) |
| `scout auth sheets` | Connect Google Sheets (one-time OAuth) |
| `scout notion-sync` | Sync pipeline to Notion |
| `scout sheets-sync` | Export to Google Sheets |
| `scout daemon start` | Run autopilot in background |
| `scout daemon stop` | Stop autopilot |
| `scout daemon status` | Check if autopilot is running |

---

## Docker

If you prefer Docker:

```bash
# Build the image
docker build -t scout .

# Run with your API key
docker run -p 8000:8000 \
  -e AI_PROVIDER=gemini \
  -e AI_API_KEY=your-key-here \
  -e AI_MODEL=gemini-2.0-flash \
  -v scout-data:/app/data \
  -v scout-config:/app/config \
  -v scout-resume:/app/resume \
  scout
```

Or with Docker Compose:

```bash
# Edit .env with your API key first
docker compose up
```

The dashboard will be at http://localhost:8000.

---

## How Scoring Works

1. **Scraping** — Scout fetches jobs from 15+ sources and filters them against your preferences (job titles, locations, keywords).

2. **AI Scoring** — Each job description is sent to your AI provider along with your resume summary. The AI returns:
   - `match_score` (0.0 to 1.0) — how well the job matches you
   - `ats_keywords` — keywords from the JD you should have on your resume
   - `missing_skills` — skills the job wants that you don't have
   - `recommended_action` — apply, manual review, or skip

3. **ATS Scoring** — When you build a tailored resume, Scout also runs a keyword-based ATS score that checks how many required/preferred keywords from the JD appear in your resume.

4. **Resume Tailoring** — The AI rewrites your resume bullets to echo the JD's language while staying truthful. It will never fabricate experience, certifications, or metrics. A fabrication detector compares the output against your master resume and warns if anything looks added.

---

## Career Domain Support

Scout works for any profession, not just tech:

| Domain | Setup | Scrapers Used | Auto-Apply |
|--------|-------|---------------|------------|
| Technology | Select "Technology" in setup | All 13 sources | Allowed |
| Healthcare | Select "Healthcare" in setup | 5 general sources | Blocked (manual review required) |
| Hospitality | Select "Hospitality" in setup | 5 general sources | Allowed |
| Education | Select "Education" in setup | 5 general sources | Blocked (manual review required) |
| General | Select "Other" in setup | 5 general sources | Allowed |

For healthcare and education, auto-apply is disabled because these professions have licensing and certification requirements that must be verified manually for each application.

---

## Optional Integrations

### Gmail (track application status)

```bash
# You need a Google Cloud project with Gmail API enabled
# Download client_secret.json to config/credentials/
scout auth gmail
```

Then run `scout email-sync` to scan for application status emails (rejections, interviews, offers).

### Notion (sync job pipeline)

1. Create a [Notion integration](https://www.notion.so/my-integrations)
2. Add `NOTION_TOKEN=your-token` to `.env`
3. Add `NOTION_JOBS_DB_ID=your-database-id` to `.env`
4. Run `scout notion-sync`

### Google Sheets (export data)

```bash
scout auth sheets
scout sheets-sync
```

---

## Troubleshooting

**Run `scout doctor` first** — it checks every component and tells you exactly what's wrong.

### Common issues

**"zsh: command not found: scout" (right after install)**
The installer adds `scout` to your PATH only for new shells. Open a new terminal, or run `source ~/.zshrc`. To run it right now without that, use the full path: `~/scout/.venv/bin/scout doctor`.

**Install one-liner fails with "curl: (56) ... 503"**
That is a temporary GitHub outage on the download host, not your machine. Retry the command (it now retries automatically). If it keeps failing, your network may block `raw.githubusercontent.com`; clone instead: `git clone https://github.com/joelkanyi/scout.git ~/scout && cd ~/scout && bash install.sh`.

**"No AI provider configured"**
Run `scout setup` and follow the prompts, or edit `.env` manually.

**Switching AI provider (e.g. to Qwen/DashScope or DeepSeek)**
Run `scout setup --reconfigure`, choose option 4 (OpenAI-compatible), and enter the base URL, key, and model.

**Resume tailoring or PDF export fails / "install Pango"**
PDF export uses WeasyPrint, which needs the Pango system library. macOS: `brew install pango`. Debian/Ubuntu: `sudo apt-get install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0`. DOCX export works without it.

**AI calls fail with a 404 / "model not available"**
Your configured model was retired by the provider. Run `scout setup --reconfigure` and pick a current model. `scout doctor` now makes a live test call and flags a dead model directly.

**Moved your data to `~/.scout` and lost your AI key**
The AI key and model live in `.env`. When migrating an old setup, move it too: `mv <old-folder>/{config,data,resume,.env} ~/.scout/`.

**"ModuleNotFoundError"**
Make sure you're in the virtual environment: `source .venv/bin/activate`

**"Frontend not built"**
Run: `cd ui && npm install && npm run build`

**Scraping returns 0 jobs**
- Check your job titles in `config/preferences.yaml` — are they too specific?
- Check your required keywords — if set, jobs must contain at least one
- Run `scout scrape` and look at the output for errors per source

**Scoring fails with "Rate limited"**
- Gemini free tier allows 15 requests/minute. If you have many jobs, scoring will take a while.
- Try `scout score --limit 10` to score in small batches.
- Or switch to Ollama (no rate limits, runs locally).

**Dashboard shows blank page**
- Make sure the frontend is built: `cd ui && npm run build`
- Or use dev mode: `scout ui --dev`

---

## Architecture

```
Scout CLI (Typer)
    |
    +-- Scrapers (13 sources) --> SQLite Database
    |                                |
    +-- AI Scorer (3 providers) -----+
    |                                |
    +-- Resume Builder (PDF/DOCX) ---+
    |                                |
    +-- Apply Bot (Playwright) ------+
    |                                |
    +-- FastAPI REST API ------------+-- React Dashboard
    |
    +-- Gmail/Notion/Sheets integrations
```

| Component | Technology |
|-----------|-----------|
| AI Engine | Gemini, Ollama, or Anthropic (your choice) |
| Job Scraping | JobSpy + 12 free APIs |
| Apply Bot | Playwright (Chromium) |
| Database | SQLite (local, zero config) |
| Web UI | FastAPI + React + Vite + Tailwind |
| CLI | Typer + Rich |
| Resume PDF | WeasyPrint + Jinja2 |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

[MIT](LICENSE)
