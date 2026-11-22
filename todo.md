# TODO: paid analysis from a video link

Goal: a customer pays, and receives the analysis they need to build their own video in HyperFrames, based on the
link they gave us. We never deliver the source video, its frames, or its transcript.

## Steps (customer journey)

1. Paste a link or upload a video on the landing page or the analyzer.
2. See the price on the pricing page (cost lines, 10% margin, no minimum).
3. Enter an email and pay by card through Stripe.
4. We analyse the video in the background (captions and timing for links, full analysis for uploads).
5. The deliverables are emailed to the customer from info@pexabo.com.
6. The customer gives the HyperFrames template and their own content to HyperFrames and renders the video.

## Done

- [x] Analyzer web app on Fly.io with a token-protected API (`/`, `/api/jobs`).
- [x] Measured analysis: transcript pace, hook, sections, cut rate, shot lengths, silences (`reverse_video.py`).
- [x] Deliverables only: `storyboard.md`, `edit_decision_list.edl`, `metrics.json`, `hyperframes_prompt.md`,
      `hyperframes_template.json`. No transcript text, no frames, no video in the delivered set.
- [x] HyperFrames template and prompts built from measured structure with placeholders (`template.py`).
- [x] Storyboard and EDL from DeepInfra vision output, with speech shown as yes or no only (`reverse_llm.py`, `deepinfra.py`).
      Needs `DEEPINFRA_API_KEY`.
- [x] URLs are never downloaded (YouTube terms). Uploads are analysed in full.
- [x] Source video and frames kept in Azure Blob for the operator under `internal/<job_id>/` (`storage.py`).
- [x] Project folders in Azure Blob, one container with a folder per project (`storage.py`).
- [x] Secrets read from Azure Key Vault (`vault.py`). Gmail credentials confirmed (sender info@pexabo.com).
- [x] Cost calculator: DeepInfra tokens, Fly.io compute and Azure storage shown line by line, 10% margin, no minimum
      (`pricing.py`). Public quote at `/api/quote` and page at `/pricing`.
- [x] Landing page at `/landing`, with the value, what you get, what we do not deliver, how it works and FAQs.
- [x] Setup guide for macOS, Windows and Linux at `/setup`.
- [x] Menus on every page: Home, Analyzer, Pricing, Setup guide, Source.
- [x] Gmail send module (`gmail.py`), tested against the real account for the sender address only.

## Missing (blocking the paid flow)

- [ ] **Stripe test mode.** Needs a test secret key (`STRIPE_SECRET_KEY`, `sk_test_…`) and a webhook signing secret
      (`STRIPE_WEBHOOK_SECRET`) set as Fly secrets. Not in the Key Vault yet.
- [ ] **Order flow.** `POST /api/orders` (email, link or upload, price from the quote), a Stripe Checkout session,
      and `POST /api/stripe/webhook` that starts the job once payment is confirmed.
- [ ] **Email on completion.** Send the five deliverables to the customer's email when the job ends (`gmail.py` is
      ready, not wired to jobs). Needs the order record to hold the email.
- [ ] **Order storage.** Orders and uploads currently live on the Fly machine disk, which is lost on restart.
      Move order records to Azure Blob or a database before real customers.
- [ ] **Privacy notice and terms** for the checkout page (what we keep, for how long, refunds).
- [ ] **Legal check** on selling analysis of linked videos. Links give captions and timing only, not the video.
- [ ] **Model keys and names.** `DEEPINFRA_API_KEY` is set. The default model names have not been checked end to end
      against the live API.
- [ ] **Frames need the DeepInfra key** today, because frame extraction runs inside the LLM step. Split it so frames
      exist without the key if needed.
- [ ] **Rendering.** The customer renders in HyperFrames themselves. We have not checked that the template renders
      with `create_video.py` end to end on a real video.
- [ ] **Analyzer page.** Its server panel may still read result fields that the API no longer returns (transcript
      segments, frames). Check and update.
- [ ] **Tests.** Some API tests (`tests/test_server.py`, `tests/test_projects.py`) need `httpx2` and do not run locally.
      CI runs them on push.
- [ ] **Deploy.** Latest commit deployed; this todo and the landing page need a deploy to be live.

## Next, in order

1. Create the Stripe test account and send the test keys as Fly secrets.
2. Build the order flow and the webhook, with tests using a stubbed Stripe.
3. Wire the email to the job's completion, sending the deliverables.
4. Move order records off the machine disk.
5. Run one paid order end to end on the test video, then check the template renders in HyperFrames.
