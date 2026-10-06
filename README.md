# NeuroQueue

**Live site: https://neuroqueue-one.vercel.app**  ·  [Launch video](submission/NeuroQueue-launch-video.mp4)  ·  [Submission document](submission/SUBMISSION.md)

AI-assisted brain MRI reporting. Our trained MRI model classifies each scan, the queue is sorted into **Urgent**,
**Review** and **Routine** in real time, and a doctor reviews, approves and finalizes an official report that the
patient can then view and download.

> **Decision support only, not a diagnosis. Every scan is reviewed by a doctor.**
> Routine means "read last", never "cleared". Nothing reaches a patient until a doctor has finalized it.

## Roles and boundaries

| Who | Does what |
|---|---|
| **Our trained MRI model** | The only classifier. Gives the class (glioma, meningioma, pituitary tumor, no tumor) and its confidence. The stored result is never edited |
| **Doctor** | Sees only the scans assigned to them. Reviews the classification, confirms or overrides it, edits, approves and finalizes the report |
| **Language model (Qwen)** | Document assistant only: words the report from doctor-confirmed fields, and powers the help assistant. Never sees the image, never classifies |
| **Patient** | Views and downloads their own finalized reports. Cannot upload scans or run the model |
| **Admin** | Uploads scans (one or many) and assigns each to a doctor and a patient. Approves doctor registrations, manages users, oversees the system |

```
 ADMIN --upload + assign doctor & patient--> validation + preprocessing --> OUR TRAINED MRI MODEL --> classification + confidence
                                                                                     |
        doctor review (confirm / override) <-- deterministic triage rules (tier) <---+
                     |
                     v
        report generator (Qwen wording or template, confirmed fields only) --> deterministic report check
                     |
                     v
        doctor approval --> FINAL REPORT (PDF, unique report ID) --> PATIENT (view / download)
```

Every step (upload, classification, review, draft, approval, patient access) is written to a hash-chained audit log.

### Alibaba Cloud services and their roles

| Service | Role in NeuroQueue |
|---|---|
| **Model Studio (Qwen) – `qwen3.8-max` text** | Words the clinical report and patient summary from the confirmed fields only (streamed, guarded) |
| **Model Studio (Qwen) – `qwen3.8-flash` text** | Help assistant and tier explanations |
| OSS (optional) | Drop-in for scan / PDF storage (see `backend/app/store/base.py`) |
| Function Compute or ECS (optional) | Hosts the backend container (see `docs/DEPLOY.md`) |

Qwen is not used for classification anywhere. The API key stays in `backend/.env` and is only used server-side.

## Run it

Requirements: Python 3.11, Node 20+.

```bash
# 1. backend
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements.txt      # Linux/macOS: .venv/bin/python
cp backend/.env.example backend/.env                                 # then fill in the keys
cd backend
../.venv/Scripts/python seed.py                                      # admin + demo doctor + demo patient
../.venv/Scripts/python -m uvicorn app.main:app --port 8000

# 2. frontend (second terminal)
cd frontend
npm install --legacy-peer-deps
npm run dev                                                          # http://localhost:3000
```

`make dev`, `make test`, `make train`, `make sim`, `make seed` wrap the same commands (on Windows use `./dev.ps1 <target>`).

Sign-in details for the seeded accounts are in `backend/.env` (`ADMIN_*`, `DEMO_DOCTOR_*`, `DEMO_PATIENT_*`).
Admin registration on the site needs `ADMIN_INVITE_CODE` from the same file.

### Demo in two minutes

1. Sign in as the demo doctor, open **Queue**, press **Load 20 demo scans**, then **Run classification**.
2. Urgent scans rise to the top. `demo_15` (a true meningioma the model calls "no tumor" at 50%) lands in Review.
3. Open it, toggle the heatmap (H), **Override** to meningioma with a reason, add size and location.
4. The report streams in, the check rows turn green, type your name and **Approve and finalize**, download the PDF.
5. Edit a draft to add "likely malignant, 45 mm" and re-run the check: it blocks, and approval is refused.
6. As admin, use **Upload scans**: add one or many images, choose the doctor and the patient. Sign in as that doctor to review and finalize, then as that patient to see the report.

### Mock mode (no network)

Set `NQ_MOCK_MODE=true` in `backend/.env`. The classifier, Qwen and voice providers are replaced with deterministic
mocks and data is kept in the local store. The whole flow, including the test suite, runs offline.

## Database: Supabase project `brain2`

Without Supabase settings the backend uses a local JSON store in `backend/data/` (fully functional, single machine).
To use Supabase:

1. Create a project named **brain2** in the Supabase dashboard.
2. Run `supabase/schema.sql` in the SQL editor.
3. In `backend/.env` set `SUPABASE_URL`, `SUPABASE_ANON_KEY` and `SUPABASE_SERVICE_ROLE_KEY`
   (Project settings → API). Alternatively run `supabase/service_account.sql` and set
   `SUPABASE_SERVICE_EMAIL` / `SUPABASE_SERVICE_PASSWORD` instead of the service-role key.
4. Restart the backend and run `python seed.py`. `GET /api/health` should report `"store": "supabase"`.

The browser never talks to Supabase. Row-level security is on for every table and the anon key can read nothing.

## Triage rules

Input: the trained model's calibrated probabilities and the wait time. Evaluated in this order; the first match
decides the tier (`backend/app/services/verifier.py`):

1. waited longer than `max_wait_min` → **Urgent** `ESCALATED_WAIT`
2. `top_prob < min_conf` → **Review** `LOW_CONFIDENCE`
3. `margin_top2 < min_margin` → **Review** `CLOSE_CALL`
4. image unlike the training data → **Review** `OUT_OF_DISTRIBUTION`
5. confident tumor class → **Urgent** `CONFIDENT_TUMOR`
6. confident no tumor, above the routine bar → **Routine** `CONFIDENT_NO_TUMOR` (otherwise Review `ROUTINE_BAR_NOT_MET`)

Thresholds live in `ml/artifacts/thresholds.json` and are tuned on the validation split only.

## Class mapping and model verification

One mapping, model output index → class: `0 glioma, 1 meningioma, 2 pituitary, 3 no_tumor`. Training writes it to
`ml/artifacts/labels.json`, `backend/app/config.py` holds the same order, and the API refuses to load a model if the
two differ. `python backend/verify_model.py` runs all 901 held-out test images through the exact serving path and
compares against the dataset folder labels: 888 correct (98.6%), matching the 98.7% recorded at training time.

## Reports: two versions from one source

The doctor's review (finding, size, location, clinical notes, symptoms, history, treatment plan, medicines, follow-up,
patient instructions, warning signs) is the single source of truth. Two separate documents are built from it:

| | Doctor report | Patient report |
|---|---|---|
| Audience | Medical professionals | The patient |
| Contains | Clinical information, model classification with probabilities, findings and impression, treatment plan, medication table, physician approval, model details | Visit summary, what the doctor found, the result explained in plain words, treatment, medicines, what to do next, follow-up, when to seek help |
| Never contains | | Clinical notes, history, probabilities, triage tier, model details, the clinical report text |

- The server decides which version to send from the signed-in role. A patient always gets the patient version,
  whatever the request asks for.
- Treatment, medicines, next steps, follow-up and warning signs appear in the patient report in the doctor's exact
  words, so a dose or instruction can never be altered. Plain-language explanations of each finding are fixed,
  hand-written texts. Anything not recorded is stated as not recorded.
- A deterministic check blocks a different tumor type, unrecorded numbers or locations, subtype names, and malignancy,
  prognosis, grading or "cleared" wording. No language model judges the report.
- Status: Draft → AI-generated draft → Under physician review → Approved and finalized.

## Accounts and security

- **Sign-up** creates an unverified account and emails a single-use link (24 h). No session until the email is verified.
- **Sessions** are a signed token in an `HttpOnly`, `SameSite` cookie. JavaScript never sees a token and none is ever
  put in a URL. Changing or resetting a password, disabling an account, or "sign out on every device" ends all sessions.
- **Password reset**: single-use link, 30 minutes, same response whether or not the address has an account.
- **Google sign-in**: the ID token is verified on the server (signature, audience, issuer). An existing account with the
  same Google-verified address is linked, not duplicated. Set `GOOGLE_CLIENT_ID` to enable; the button is hidden otherwise.
- **Throttling**: per-IP and per-address limits on sign-in, sign-up, verification and reset; 5 wrong passwords lock
  sign-in for that address for 15 minutes.
- **CSRF / CORS**: state-changing requests from any origin other than the configured site are refused; CORS lists
  explicit origins only. The WebSocket refuses other origins.
- **Headers**: Content-Security-Policy, `nosniff`, frame protection, `Referrer-Policy`, `Permissions-Policy`
  (microphone for this site only), HSTS in production, `Cache-Control: no-store` on API data.
- **Input**: request bodies reject unknown fields and enforce length limits; uploads are checked by content, not extension.
- **Email**: set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` to send real email. Without them,
  emails are kept in a development outbox that only an admin can open (Admin → Users). It disappears once SMTP is set.
- **Production**: set `COOKIE_SECURE=true`, serve over HTTPS, set `APP_URL` and `CORS_ORIGINS` to the real site.

## Model (`/ml`)

`python -m ml.train` runs the whole reproducible pipeline (fixed seed, config logged to `train_config.json`):
perceptual-hash de-duplication → stratified train / val / test → EfficientNet-B0 fine-tune → temperature scaling →
threshold grid search on validation → one evaluation on the held-out test set → ONNX export → 20 demo scans from test.

Results of the committed run (Kaggle "Brain Tumor MRI Dataset", CC0, 7,200 images):

| | |
|---|---|
| Duplicates removed before splitting | 1,144 (plus 49 images with conflicting labels) |
| Test accuracy (901 held-out scans) | 98.7% |
| Tumor recall (tumor vs no tumor) | 99.1% |
| Per-class recall | glioma 98.9%, meningioma 98.0%, pituitary 99.2%, no tumor 98.5% |
| Calibration error (ECE) | 0.004 after temperature scaling (0.008 before) |
| Misclassified test scans | 12, of which 11 were routed to Review or Urgent by the verifier |
| True tumors tiered Routine on test | 1 of 765 |
| Sent to Review | 4.6% of test scans |

The model is not always right, which is why a doctor reviews every scan. The one true tumor that reached Routine is why Routine scans are still read. Full numbers: `ml/artifacts/metrics.json`.
`ml/NeuroQueue_training.ipynb` runs the same pipeline on a free Kaggle / Colab GPU.

## Simulation (`/sim`)

`python sim/queue_simulation.py` compares first-come-first-served with NeuroQueue ordering using the real verifier on
held-out test predictions. With the default assumptions (9 scans/hour, 6 minutes per read, 25% true tumors, one
radiologist, 8-hour day, 200 simulated days) urgent scans wait a mean of 6.5 minutes instead of 17.8, and 11.7 instead
of 43.3 at the 90th percentile; no-tumor scans wait longer (21.1 vs 17.4 minutes mean). Every assumption is written
into the output. **These are simulated waiting times, not clinical outcomes.**

## Tests

```bash
cd backend && ../.venv/Scripts/python -m pytest tests -q        # 84 tests, offline
```

Covers every verifier rule and the rule order, threshold edges, escalation, report-check contradiction and
invented-detail cases, the live stream guard, the sign-off gate, audit-chain tamper detection, PDF export, provider
contracts, access control for all three roles, and one end-to-end run from upload to signed PDF. Safety tests assert
that nothing can be signed without a review, a blocked report cannot be released, and no status means "cleared".

## API

```
POST /api/auth/register | /api/auth/login        GET /api/auth/me
GET  /api/users   POST /api/users/{id}/status    (admin: approve / reject / disable)
POST /api/scans/batch            doctor only: images + exam details -> Scan[] (pending)
POST /api/scans/{id}/classify    POST /api/queue/process      (streamed jobs)
GET  /api/queue                  scans ordered by tier, then wait time
GET  /api/scans/{id}             scan + prediction + verifier reasons + next steps
GET  /api/scans/{id}/image | /heatmap | /pdf
POST /api/scans/{id}/review      confirm or override (logged)
POST /api/scans/{id}/draft       streamed draft + report check
POST /api/scans/{id}/check       re-check after an edit
POST /api/scans/{id}/sign        approve and finalize: only if reviewed, check passed and doctor named
GET  /api/my/scans               patient view: own examinations and finalized reports only
GET  /api/metrics  /api/audit  /api/stats/overview  /api/health
POST /api/assist/chat            streamed help assistant      GET /api/assist/voice-token
WS   /ws                         job_started | job_progress | job_partial | job_token | job_done | job_failed, scan_updated, ...
```

Errors are always `{code, message, hint}`. Stack traces and secrets are never returned.

## Limits

- Trained on public 2D MRI images from a single dataset; a real deployment needs local validation.
- No patient history or clinical context is used.
- Performance on other scanners, sequences and protocols is unknown.
- Dataset labels are the ground truth the model learned from; they are not a clinical diagnosis for a new patient.
- Simulation numbers depend entirely on the stated assumptions.
- Any approved doctor can open any scan in the shared reading queue; there is no per-doctor patient assignment.
- Rate limits and sign-in lockouts are held in memory, so they reset on restart and do not span multiple servers.
- This is hackathon-grade security work, not a certified or audited medical system.
- Not a medical device.

## Support

Email 2200031362csehh@gmail.com · Phone +971 528813637
