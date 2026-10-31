# ADR-0005: Model and data licences; research-only training data behind the registry with a caveat

> Copy of `docs/adr/ADR-0005-licences.md` from the maintainers' working repo at `e846ede`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted (stakeholder-proxy, 2026-10-28; operator ask #336 decided 2026-10-28: accept with the caveat;
licence table re-read 2026-10-29, TICKET-029)
Date: 2026-10-28

## Context
the team wrote on #46 that non-commercial licences are excluded because the result is for an app.
RTMPose code and weights are reported as Apache-2.0 on #46, but its body7 training data includes datasets
with research-only terms. MotionBERT code is reported as Apache-2.0 on #46, and Muse noted that such
lifters are usually trained on Human3.6M, whose terms are research-only. SAM 3D Body weights on the mirror
used here carry the "SAM License" (LICENSE file fetched at setup). `facebook/sam2.1-hiera-large` reports
`apache-2.0` on Hugging Face (fetched at setup).

## Options Considered
### Option 1: exclude every model with research-only training data
- Pros: no caveat. Cons: no CPU backend and no fast 2D for the ladder. Effort: Low.
### Option 2: ship them behind the registry with a caveat in provenance and the README
- Pros: the team decides with numbers in hand; nothing is hidden. Cons: a caveat to keep current. Effort: Low.

## Decision
Option 2. RTMPose and MotionBERT ship behind the backend and lifter registries, never as the GPU default,
with the caveat written in `provenance.licence_notes` of every output they touch and in the README. Every
model is listed in one table in the README and here, kept current by TICKET-029. Operator ask #336 is decided
(2026-10-28): the operator accepts RTMPose and MotionBERT with the recorded caveat.

Re-read on 2026-10-29 (TICKET-029) from the source in each row. A source that refused is marked with its HTTP status; every other source answered HTTP 200. This table and the README table are identical; it records what the texts say and is not a legal opinion.

| Model or data | Used for | Licence, as read | Source |
|---|---|---|---|
| SAM 3D Body (`jetjodh/sam-3d-body-dinov3` mirror at `1f026b2`: `model.ckpt`, `assets/mhr_model.pt`) | `gpu` backend 3D | SAM License (last updated November 19, 2025): use, copy, modify and distribute, with no non-commercial term; redistribution only under the same licence with a copy of it; no activity subject to ITAR and no end use barred by trade controls (military or warfare, nuclear, espionage, guns or illegal weapons). Outputs appear only in the warranty disclaimer and the litigation clause. | mirror `LICENSE`, identical to `facebookresearch/sam-3d-body` `LICENSE`; Hugging Face card metadata `license: other`, `sam-license` |
| SAM 2.1 hiera-large (`facebook/sam2.1-hiera-large`) | `local-open` tracker | Apache-2.0 | Hugging Face card metadata `license: apache-2.0`; `facebookresearch/sam2` `LICENSE` |
| SAM 3 and SAM 3.1 weights (`facebook/sam3`; `facebook/sam3.1` at `daa6319`, `sam3.1_multiplex.pt`) | `local-sam31` tracker | Gated with manual approval; card metadata `license: other`; the access form asks the user to accept "the terms of the license". The weights' own `LICENSE` was not read. The SAM 3 code that loads them, which also carries the SAM 3.1 code, is under the SAM License of November 19, 2025: the SAM 3D Body text without its patent clause. | Hugging Face API for both repos; their `LICENSE` files: HTTP 401 without a token; `facebookresearch/sam3` `LICENSE` and `README.md` |
| SAM 3.1 on the Meta Model API (`sam-3.1`) | `api-sam31` tracker | Meta Model API Terms of Service (last updated October 9, 2026): the user owns Inputs and Outputs (4.1); the services are meant for commercial use (1); SAM 3.1 is a Standard Model (Model Designation and Geographic Use Policy, last updated October 12, 2026), and Meta does not use content sent to Standard Services to train its models (5.1); no access for third parties, API key included, other than end users through your own product (10); Outputs may not train a competing model (10); access is for a limited period (15.1). | `dev.meta.ai/legal/terms-of-service` (reached from `llama.developer.meta.com/legal/terms-of-service`); `dev.meta.ai/legal/geographic-use-policy` |
| ViTDet Cascade Mask R-CNN ViT-H (`model_final_f05665.pkl`) through detectron2 | `gpu` backend person boxes | detectron2 code: Apache-2.0. The ViTDet project page names no licence for its weights. detectron2's `MODEL_ZOO.md` puts the models it lists under CC BY-SA 3.0; this checkpoint is listed on the ViTDet page, not there. | `facebookresearch/detectron2` `LICENSE`, `README.md`, `MODEL_ZOO.md`, `projects/ViTDet/README.md` |
| MoGe-2 (`Ruicheng/moge-2-vitl-normal` at `cb0e8bb`) | `gpu` backend field of view | MIT, except the DINOv2 code in `moge/model/modules/dinov2`, which is Apache-2.0 (both texts in one `LICENSE` file); model card metadata `license: mit` | `microsoft/MoGe` `LICENSE` and `README.md`; Hugging Face API |
| RTMPose-x and its YOLOX person detector, through rtmlib | `cpu` backend 2D; person boxes for `local-open` and `bytetrack` | rtmlib and MMPose code: Apache-2.0. The RTMPose page names no separate weight licence. The weights are trained on body7 (AI Challenger, MS COCO, CrowdPose, MPII, sub-JHMDB, Halpe, PoseTrack18), which, as recorded on #46, includes datasets with research-only terms (the caveat above, written into `cpu` backend outputs). | `Tau-J/rtmlib` `LICENSE`; `open-mmlab/mmpose` `LICENSE` and `projects/rtmpose/README.md` |
| MotionBERT-Lite (`walterzhu/MotionBERT` at `370a919`, `FT_MB_lite_MB_ft_h36m_global_lite`) | `motionbert` lifter | Apache-2.0, the same `LICENSE` in the code repo and the weights repo. The checkpoint name marks a fine-tune on Human3.6M, whose free licence is "limited to academic use only", with commercial licences on request from its authors (the caveat above). | `Walter0807/MotionBERT` `LICENSE`; Hugging Face `LICENSE`; Human3.6M licence page `vision.imar.ro/human3.6m/eula.php` |
| ByteTrack (re-implemented in `part2/trackers/bytetrack.py`) | `bytetrack` tracker | MIT, copyright 2021 Yifu Zhang | `ifzhang/ByteTrack` `LICENSE` |
| COCO val2017 person keypoints | second one-person scored set | Annotations: CC BY 4.0, COCO Consortium. Images: the Consortium does not own them, and their use must follow the Flickr Terms of Use. The selection keeps licence ids 4 to 8 (commercial use allowed); the kept images are Attribution (14), Attribution-ShareAlike (4) and Attribution-NoDerivs (2). The image bytes stay out of the repo. | `cocodataset.org/dataset/termsofuse.htm`; per image `fixtures/input/coco/SOURCE.md`; the rule in `fixtures/input/coco/SELECTION.md` |
| Pexels clips: class fixture 8480627 (Yan Krukau), one-person fixture 6019962, dance 8956007, stock takes 5034562, 5034577 and 8837221 | scored inputs, dance demo, stock takes | Pexels licence. The fixture source files (clips downloaded 2026-10-27) record it as free to use with no attribution required; attribution is given anyway. The licence text was not re-read. | `pexels.com/license` and the clip pages: HTTP 403 (Cloudflare challenge); per clip `fixtures/input/class/SOURCE.md`, `fixtures/input/single/SOURCE.md`, `fixtures/output/stock/*/SOURCE.md` |
| Squat clip by FitnessScape (Wikimedia Commons) | `fixtures/output/single/`, `demos/viewer-squat.html` | CC BY 3.0 | Commons API file metadata (`LicenseShortName`, `UsageTerms`) |

### What the re-read changed (2026-10-29)
- RTMPose: #46 reported "Apache-2.0 code and weights". The rtmlib and MMPose code is Apache-2.0; the RTMPose
  page states no separate licence for the weights, so the table no longer claims one.
- ViTDet and MoGe-2 were "measured at TICKET-029": now recorded. The ViTDet checkpoint has no licence on its
  project page, and detectron2's CC BY-SA 3.0 model-zoo statement covers the models `MODEL_ZOO.md` lists, which
  do not include it. Part 2 downloads it at setup and neither commits nor redistributes it.
- SAM 3.1 weights: the weights' own `LICENSE` answers HTTP 401 without a token and was not read. The
  `local-sam31` provenance label "SAM License (gated weights)" rests on the SAM 3 code licence and the gate
  form, not on that file. Open item: the account that holds the access grant can read it on the model page.
- Meta Model API terms: read (October 9, 2026 version). SAM 3.1 is a Standard Model, so content sent with it is
  not used to train Meta's models, and the user owns the outputs.
- ByteTrack: MIT, confirmed. MotionBERT: Apache-2.0, confirmed; the Human3.6M terms behind the caveat were read.
- COCO: the filter allows licence ids 4 to 8; the kept images use only Attribution, Attribution-ShareAlike and
  Attribution-NoDerivs.
- Pexels: the licence page and the clip pages refused (HTTP 403), so the Pexels row stays as the fixture
  source files recorded it.

## Consequences
- **Positive**: the team sees the trade-off with numbers.
- **Negative**: a reader may skip the caveat; it is repeated in every output's provenance.
- **Neutral**: the operator accepted on #336 (2026-10-28), so Option 1 is not taken; a later reject would
  disable the CPU backend and rung 1 by default.

## Assumptions
- ASM-012 (MotionBERT weights downloadable without a login).

## Reversal Cost
Low: registry defaults and the README table.

## Pre-Mortem (MANDATORY)
1. The team ships the app with a research-only model by default. Likelihood: L, Impact: H. Mitigation: GPU
   default; caveat in provenance; DONE? names it.
2. A licence recorded from a thread is wrong. Likelihood: M, Impact: M. Mitigation: TICKET-029 re-reads each
   LICENSE file and corrects the table. Outcome (2026-10-29): one claim corrected (RTMPose weights), see
   "What the re-read changed".
3. The SAM License restricts redistribution of outputs. Likelihood: L, Impact: M. Mitigation: TICKET-029 reads
   the terms and records the answer. Outcome (2026-10-29): its conditions bind the SAM Materials and derivative
   works of them; outputs appear only in the warranty disclaimer (section 3) and the litigation clause
   (section 5b). Recorded as read, not as a legal opinion.

## Dissent (MANDATORY)
Reviewed by: setup lane (architect role)
- the team's exclusion rule argues for Option 1: the default stays GPU; the operator accepted
  on #336 with the caveat, and a teammate objection still overrides (ADR-0007).
- Training-data terms are legally unclear: recorded as a caveat, not a legal opinion.
- A table can drift: one owner ticket (TICKET-029).

## Code Backlinks (updated as code is written)
- `part2/provenance.py`, README "Models and licences".
