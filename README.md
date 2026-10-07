# Citation Tracker 🔍📊

Cross-check a researcher's citations between **Google Scholar** and **Scopus** to detect and report citations that are indexed on Scopus but **untracked** in Scopus's citation network.

Outputs an actionable CSV report and pre-drafted cover letter ready to submit directly to Elsevier/Scopus Customer Assistance.

---

## 🎯 The Problem

Often, Paper **B** cites Paper **A**. Both **A** and **B** are properly indexed in Scopus, and Google Scholar recognizes the citation. However, due to indexing glitches, reference parsing errors, or name variants, Scopus fails to link **B** $\rightarrow$ **A**. As a result, your Scopus citation count and h-index remain lower than they should be.

**Citation Tracker** automates the entire detection process:
1. Fetches all your publications indexed in Scopus.
2. Retrieves the citing papers for each of your publications from Google Scholar.
3. Checks whether each citing paper is also indexed in Scopus.
4. Identifies the exact papers where **both are in Scopus**, but Scopus **failed to link the citation**.
5. Formats the results into an Elsevier-ready CSV file with all required EIDs, DOIs, and verification text.

---

## 🚀 Quick Start

### 1. Installation

Using `uv` (recommended):
```bash
git clone https://github.com/your-username/citation-tracker.git
cd citation-tracker
uv sync
```

Or install using `pip`:
```bash
pip install -e .
```

### 2. Configure Elsevier API Key (Free)

Elsevier provides a free API key with 20,000 queries per week:
1. Go to [https://dev.elsevier.com/apikey/create](https://dev.elsevier.com/apikey/create) and sign in.
2. Generate an API Key.
3. Configure it using the interactive setup command:
   ```bash
   uv run citation-tracker setup
   ```
   *(Or simply create a `.env` file containing `ELSEVIER_API_KEY=your_key_here`)*

To verify that your key is working:
```bash
uv run citation-tracker test-api
```

---

## 💻 Usage

### Option A: Using Scopus Author ID and Google Scholar ID (Recommended)

```bash
uv run citation-tracker check \
  --scopus-id 57201234567 \
  --scholar-id qc6CJjYAAAAJ
```

- **Scopus Author ID**: Found in your Scopus profile URL (`...authorId=57201234567`).
- **Google Scholar Profile ID**: Found in your Google Scholar URL (`...user=qc6CJjYAAAAJ`).

### Option B: Using ORCID and Google Scholar ID

```bash
uv run citation-tracker check \
  --orcid 0000-0002-1825-0097 \
  --scholar-id qc6CJjYAAAAJ
```

### Option C: Using Researcher Name (Interactive)

If you don't know your IDs, search by name:
```bash
uv run citation-tracker check --name "Mario Rossi"
```
The CLI will search Scopus and Scholar, present matching profiles, and let you select yours.

You can also look up IDs in advance using:
```bash
uv run citation-tracker search-author --name "Mario Rossi"
```

### Option D: Using an Exported Scopus CSV

If you have already downloaded your publications from Scopus (scopus.com $\rightarrow$ Author Profile $\rightarrow$ Export all to CSV):
```bash
uv run citation-tracker check \
  --scopus-csv path/to/scopus_export.csv \
  --scholar-id qc6CJjYAAAAJ
```

---

## 📁 Generated Outputs

When the scan completes, three files are created in your working directory:

1. **`missing_citations_for_scopus.csv`** *(Most Important)*:
   Contains only the lost citations where:
   - Your paper is indexed in Scopus.
   - The citing paper is indexed in Scopus.
   - The citation exists on Google Scholar.
   - The citation link is currently **missing** in Scopus.

   Includes columns:
   - `Cited_Paper_Title`, `Cited_Paper_DOI`, `Cited_Paper_Scopus_EID`, `Cited_Paper_Scopus_URL`
   - `Citing_Paper_Title`, `Citing_Paper_Scopus_EID`, `Citing_Paper_Scopus_DOI`, `Citing_Paper_Scopus_URL`
   - `Scopus_Support_Request` (pre-drafted text for each citation)

2. **`citations_report.csv`**:
   The full audit log of all examined citations categorized into:
   - `MISSING_IN_SCOPUS`
   - `TRACKED_IN_SCOPUS`
   - `CITING_NOT_IN_SCOPUS` (e.g. preprints, theses, non-indexed venues)

3. **`scopus_support_letter.txt`**:
   A pre-written, formal cover letter that you can copy and paste into the Elsevier Support contact form.

---

## 📩 Submitting to Scopus Support

Once you have your `missing_citations_for_scopus.csv`:

1. Open the [Elsevier Scopus Support Hub - Missing Citations Form](https://service.elsevier.com/app/answers/detail/a_id/28221/supporthub/scopus/).
2. Select **Contact Us** $\rightarrow$ **Missing Citations**.
3. Attach the generated `missing_citations_for_scopus.csv`.
4. Copy and paste the text from `scopus_support_letter.txt` into the description.
5. Submit the ticket. Scopus typically processes and updates these citations within 2–4 business days.

---

## ⚙️ Advanced Options

| Flag | Description | Default |
|---|---|---|
| `--scholar-delay <seconds>` | Delay between Google Scholar requests to prevent CAPTCHAs | `2.5` |
| `--scholar-cookie <cookie>` | Browser cookie header from Google Scholar | `None` |
| `--max-papers <n>` | Limit number of papers to inspect (useful for testing) | All |
| `--no-cache` | Disable query caching | `False` |
| `--clear-cache` | Wipe local cache (`.cache/citation_tracker/`) before running | `False` |
| `--output <path>` | Custom path for full CSV report | `citations_report.csv` |
| `--missing-output <path>` | Custom path for missing citations CSV | `missing_citations_for_scopus.csv` |
| `--cover-letter <path>` | Custom path for support letter | `scopus_support_letter.txt` |

### Avoiding Google Scholar CAPTCHAs
- **Automatic Caching**: Citation Tracker automatically saves all fetched results to `.cache/citation_tracker/`. If a run is ever interrupted by Google Scholar, simply re-running the command resumes where it left off without re-querying already processed papers.
- **Polite Delays**: The default delay is 2.5 seconds with randomized jitter. If you have a large bibliography, you can increase this with `--scholar-delay 4.0`.
- **Browser Cookies**: If you hit a CAPTCHA in your network, solve it once in your browser, copy your `Cookie` header from browser Developer Tools (Network tab), and pass `--scholar-cookie "YOUR_COOKIE"`.

---

## 🧪 Testing

Run the test suite with:
```bash
uv run pytest
```