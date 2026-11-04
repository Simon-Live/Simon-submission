<!--
Drafting notes (removed before the page is served). Register LEG-H2. The services come from the code on lane/golive-candidate as prod runs it (docs/legal/data-flow-inventory.md).
Prod reads the Meta and Baseten keys only with the muse switch on (part7/keys.py MUSE_KEYS, docs/specs/muse-prod.md); it makes no Hugging Face
call with user data, and every Part 2 run and every caption goes to the operator's Modal workspace (docs/specs/serverless-compute.md).
Operator acceptance, 3 November 2026: no lawyer reviewed this page. The operator accepted it without one, and the review line
was removed as the record of that acceptance. Names come from part7/legal_pages.py TOKENS.
Modal: https://modal.com/legal/dpa, https://modal.com/legal/terms (creating an account accepts it),
https://modal.com/docs/guide/region-selection, https://modal.com/docs/guide/data-residency (Volumes rest in United States object storage
with no region setting), https://modal.com/docs/guide/security (logs 1 day on Starter), https://modal.com/docs/guide/volumes (no erasure deadline).
Modal's sub-processor list (https://trust.modal.com/subprocessors) served no readable list on 3 November 2026, so the page names none.
Resend: https://resend.com/legal/dpa, https://resend.com/docs/dashboard/domains/regions.
Cloudflare: https://www.cloudflare.com/terms/, https://www.cloudflare.com/cloudflare-customer-dpa/,
https://www.cloudflare.com/trust-hub/gdpr/, https://www.cloudflare.com/network/. Providers: claude-template ADR-0024,
ADR-0025, docs/prod/registry-block.yaml. Add any provider that forwards the contact mail. Nothing on file
shows the Resend or Cloudflare account has accepted those terms; the wording states how each DPA takes effect.
The data privacy framework participant list could not be read, so the framework wording is each company's own claim.
Hetzner and R2: the hosting and backup decision relayed by the orchestrator on 3 November 2026. Hetzner company and agreement: https://www.hetzner.com/legal/terms-and-conditions/ and the operator answers file (standard DPA v1.1 of February 10, 2025, created 3 November 2026).
R2: https://developers.cloudflare.com/r2/reference/data-location/ (jurisdiction fixed at bucket creation),
https://developers.cloudflare.com/r2/buckets/bucket-locks/ and https://www.cloudflare.com/cloudflare-customer-dpa/ (its Services
are all Cloudflare cloud solutions; it does not name R2, and the Service-Specific Terms were not read).
Nothing on file shows the bucket exists. Backup contents: prod/statetool.py NOT_BACKED_UP.
No Part 2 tracking frame to Meta: part7/licence_gates.py tracker, AC-SC5, tests/part7/test_serverless_tracker_gate.py. Real Modal runs were made on the app at d5536a5b; no record on file checks this on real Modal (docs/legal/open-items.md).
Cloudflare roles: claude-template ADR-0024 (DNS, TLS at the edge, named tunnel), docs/prod/registry-block.yaml, prod/backup.sh. Mail: the operator answers file names Cloudflare Email Routing to the operator's own mailbox.
The prod start check (lane compute, part7/legal_drafts.py) refuses this page while it holds an operator placeholder or
the review banner. Keep every placeholder on one line in its upper case form so the check finds it.
-->
# Who processes your data

Last updated 4 November 2026.

| Service | What it does for Simon | Data it receives | Location | Safeguard and contract |
|---|---|---|---|---|
| Modal Labs, Inc. | processes videos and pose data: runs, on graphics processors in the Modal workspace {{COMPANY_NAME}} pays for, the AI models that find the people in each take, their joints in 2D and 3D and their 3D body mesh, and writes down the speech of a trainer recording for its captions; makes a 3D model from a photo or picture a person sends; converts a 3D model file a person uploads and adds a skeleton to one that has none | the video of the take, the sound of a trainer recording, the joint positions and body meshes made from them, a photo or picture sent to make a 3D model with the model made from it, and a 3D model file a person uploads with the model made from it | United States: Modal Labs, Inc., a Delaware corporation, routes requests through Virginia. The computers may run in any region Modal uses, but a take's files rest in Modal's United States storage during processing, whatever the region. Simon removes them when the job ends or the take is deleted. Modal gives no date by which removed files are erased from its own systems, and keeps its logs for up to 1 day on its Starter plan | Modal's data processing addendum, part of Modal's agreement with {{COMPANY_NAME}}, which is Modal's customer and needs no separate signature; standard contractual clauses for EU, UK and Swiss data |
| Resend (Plus Five Five, Inc.) | sends the sign-in email and the challenge invitation email | email address, sign-in code; for an invitation, the invited address, the inviter's display name and the challenge title | United States: Plus Five Five, Inc., San Francisco, which stores email metadata and logs in the United States | Resend's data processing addendum, which takes effect with Resend's agreement and needs no separate signature; standard contractual clauses for EU, UK and Swiss data; Resend says it complies with the EU-US Data Privacy Framework and its UK extension |
| Cloudflare, Inc. | runs Simon's DNS, ends its TLS connections and runs the tunnel that carries every request to the server | network address, and every request and answer as it passes, an uploaded video included | United States: Cloudflare, Inc., San Francisco, with a network in more than 100 countries | Cloudflare's data processing addendum, part of its self-serve agreement by reference; standard contractual clauses for EU, UK and Swiss data; Cloudflare says it is certified under the EU-US and Swiss-US Data Privacy Frameworks and the UK extension |
| Cloudflare R2 (Cloudflare, Inc.) | stores Simon's encrypted backups | account and catalog data, kept takes of people who opted in and 3D models, encrypted before it leaves Simon's server with a key only {{COMPANY_NAME}} holds | European Union: an R2 bucket in the EU jurisdiction, which Cloudflare says keeps its objects there | Cloudflare's data processing addendum, as above |
| Hetzner Online GmbH | hosts the server that runs the app and keeps its live data | everything Simon keeps on that server: videos, body measurements, account data | Germany: Hetzner Online GmbH, Gunzenhausen; the server is in Falkenstein | Hetzner's data processing agreement with {{COMPANY_NAME}} |
| Cloudflare Email Routing (Cloudflare, Inc.) | passes on mail sent to a simon.live address | the message and the sender's address | United States: Cloudflare, Inc., as above; the mail then reaches the mailbox that reads Simon's mail | Cloudflare's data processing addendum, as above |

| Meta Platforms, Inc. | runs Muse Spark, Muse Wonder and SAM 3.1 through its Model API, for the features listed under "What goes to Meta" in the [privacy policy](privacy); Muse Image is not called while "You, doing it right" is switched off | video, frames and measurements as listed there, which can show biometric data | Meta's terms do not name a location | Meta Model API Terms of Service and Meta Global Processor Terms. Meta's terms give no retention limit: it keeps data as needed. |
| Baseten | runs Meta's Muse Spark Open model to phrase feedback | the measured fault: which joint, how far off, when | Baseten's terms do not name a location for this service | Baseten's terms and data processing addendum |

Not used in this version: Meta MMS-TTS voices (your browser speaks the feedback), Google Fonts and
any outside script host (fonts and code are served by Simon itself). Google MediaPipe runs inside your browser for
Live check and sends nothing.
