# Architecture

Simon is seven parts. Parts 1 to 6 are folders under `modules/` in this repo (ADR-0008), and Part 7 runs each one as a
separate process and passes files between them. The three diagrams below show the parts and their contract files,
one follow job from upload to result, and where the trust boundaries sit. Every node has a row in the table under its
diagram that links to the file and line it stands for.

`tools/arch_check.py` keeps this page honest. It fails CI when a diagram names a part, file, symbol or contract that
the code no longer has; `python3 tools/arch_check.py --fix` moves a link to the symbol's new line.

## System view

Each arrow carries the contract file a part writes and, where its schema fixes one, the format string. Dotted arrows
show where each model runs.

```mermaid
flowchart LR
  WEB["Browser: web/ app"]
  P7["Part 7: server, job queue, GPU lock"]
  P1["Part 1: keyframes"]
  P2["Part 2: images to 3D"]
  P3["Part 3: skeleton"]
  P4["Part 4: animation"]
  P5["Part 5: fault analysis"]
  P6["Part 6: catalog and player"]
  GPU[("Local GPU: SAM 3D Body in the warm Part 2 worker")]
  MMA[("Meta Model API: Muse Spark 1.3, SAM 3.1")]
  BT[("Baseten: Muse Spark Open")]
  WEB -->|"HTTP: api/uploads, api/follow, api/jobs"| P7
  P7 -->|"runner.run: one process per call"| P1 & P2 & P3 & P4 & P5
  P7 -->|"reverse proxy: catalog/"| P6
  P1 -->|"keyframes.json<br/>simon.keyframes/part1"| P3
  P2 -->|"pose3d.json"| P3
  P2 -->|"tracks.json"| P7
  P3 -->|"skeleton.json<br/>simon.skeleton/1"| P4
  P3 -->|"keyframes.v1.json<br/>simon.keyframes.v1"| P4
  P4 -->|"animation.json<br/>simon.animation.v1"| P6
  P6 -->|"animation.json, the expected movement"| P5
  P3 -->|"follower.json<br/>simon.animation.v1"| P5
  P5 -->|"analysis.json<br/>simon.analysis.v1"| P7
  P1 -.->|"phases and tracking"| MMA
  P2 -.->|"SAM 3.1 tracking"| MMA
  P2 -.->|"3D pose"| GPU
  P5 -.->|"one sentence per fault"| BT
```

The trainer's recording takes Parts 1, 2, 3 and 4 and lands in Part 6's catalog. A student's take takes Parts 2, 3
and 5. When the Meta Model API refuses Part 1, Part 3's every-10 keyframes stand in for it.

| Node | Code | Symbol |
|---|---|---|
| WEB | [web/api.js:53](../web/api.js#L53) | `request` |
| P7 | [part7/server.py:75](../part7/server.py#L75) | `App` |
| P1 | [part7/parts/p1_keyframes.py:70](../part7/parts/p1_keyframes.py#L70) | `run` |
| P2 | [part7/parts/p2_pose.py:632](../part7/parts/p2_pose.py#L632) | `run` |
| P3 | [part7/parts/p3_skeleton.py:139](../part7/parts/p3_skeleton.py#L139) | `part4` |
| P4 | [part7/parts/p4_animate.py:50](../part7/parts/p4_animate.py#L50) | `run` |
| P5 | [part7/parts/p5_analyse.py:95](../part7/parts/p5_analyse.py#L95) | `run` |
| P6 | [part7/parts/p6_catalog.py:38](../part7/parts/p6_catalog.py#L38) | `Child` |
| GPU | [part7/p2_worker.py:157](../part7/p2_worker.py#L157) | `Pool` |
| MMA | [part7/keys.py:12](../part7/keys.py#L12) | `KEY_NAMES` |
| BT | [part7/parts/p5_analyse.py:84](../part7/parts/p5_analyse.py#L84) | `phrasing_args` |

## One follow job

A student's take, from the upload to the result. Times are the measured figures in
[docs/evaluation.md](evaluation.md), section "Latency": staging job summaries of 2026-10-31 for the whole job and the
GPU wait, and a three-run benchmark on an RTX 5090 (commit `1d54206`) for the Part 2 step.

```mermaid
sequenceDiagram
  participant WEB as Browser
  participant SRV as Server
  participant Q as Job queue
  participant JOB as Follow job
  participant LOCK as GPU lock
  participant W as Warm Part 2 worker
  participant P2 as Part 2
  participant P3 as Part 3
  participant P5 as Part 5
  WEB->>SRV: POST api/follow with the upload id
  SRV->>Q: submit the follow job
  Q->>JOB: run the follower chain
  JOB->>LOCK: acquire (GPU wait median 68 s, 4 jobs)
  JOB->>W: lease the worker socket
  JOB->>P2: run --worker, then doctor on pose3d.json
  Note over P2: warm 51.7 s mean, cold 97.1 s mean
  P2-->>JOB: pose3d.json
  JOB->>LOCK: release
  JOB->>P3: --view part5 --fps 30, then doctor on follower.json
  Note over P3: about 0.3 s
  JOB->>P5: loader check, analyse, then doctor on analysis.json
  Note over P5: 1 to 10 s
  P5-->>JOB: analysis.json
  JOB-->>Q: done
  WEB->>SRV: GET api/jobs/id until done
  Note over WEB,P5: whole job median 164 s, range 105 to 216 s (6 jobs)
```

| Node | Code | Symbol |
|---|---|---|
| WEB | [web/api.js:53](../web/api.js#L53) | `request` |
| SRV | [part7/server.py:766](../part7/server.py#L766) | `_Handler._follow` |
| Q | [part7/jobs.py:447](../part7/jobs.py#L447) | `JobQueue.submit` |
| JOB | [part7/chain.py:420](../part7/chain.py#L420) | `follower` |
| LOCK | [part7/gpu_lock.py:423](../part7/gpu_lock.py#L423) | `acquire` |
| W | [part7/p2_worker.py:644](../part7/p2_worker.py#L644) | `lease` |
| P2 | [part7/parts/p2_pose.py:632](../part7/parts/p2_pose.py#L632) | `run` |
| P3 | [part7/parts/p3_skeleton.py:229](../part7/parts/p3_skeleton.py#L229) | `part5` |
| P5 | [part7/parts/p5_analyse.py:95](../part7/parts/p5_analyse.py#L95) | `run` |

The doctor after each part is that part's own check of the file it wrote (`p2_pose.doctor`, `p3_skeleton.doctor`,
`p5_analyse.doctor`). A failed doctor stops the job with the part named.

## Trust boundaries

Everything a browser sends is untrusted. Keys stay in a folder the user creates, every part's log is redacted, and
Part 1's key file exists only for the length of its call. An uploaded 3D model is parsed only inside the converter
jail.

```mermaid
flowchart LR
  subgraph Client["Browser, untrusted"]
    WEB["web/ app"]
  end
  subgraph Server["part7 serve process"]
    SRV["HTTP handler"]
    AUTH["Optional sign-in"]
    KEYS["Keys folder, redacted from logs"]
    CONV["Model upload: writes the spool only"]
  end
  subgraph Parts["Part subprocesses, own process group"]
    RUN["runner.run with timeout"]
  end
  subgraph Supervisor["Converter supervisor, a separate process"]
    SUP["Validates each spool request"]
  end
  subgraph Jail["Converter jail: no network, read-only, user 65534"]
    JAIL["Blender, then FBX2glTF for an FBX, fixed command lines"]
  end
  subgraph Egress["Egress"]
    MMA["Meta Model API"]
    BT["Baseten"]
  end
  WEB -->|"HTTP"| SRV
  SRV --> AUTH
  SRV --> RUN
  KEYS -->|"keys"| RUN
  SRV --> CONV
  CONV -->|"spool folder"| SUP
  SUP -->|"docker run"| JAIL
  RUN -->|"Part 1, Part 2"| MMA
  RUN -->|"Part 5"| BT
```

The web server has no Docker access. The supervisor is a separate process that watches the spool and starts the
container (ADR-0017).

| Node | Code | Symbol |
|---|---|---|
| WEB | [web/api.js:53](../web/api.js#L53) | `request` |
| SRV | [part7/server.py:274](../part7/server.py#L274) | `_Handler._route` |
| AUTH | [part7/auth.py:217](../part7/auth.py#L217) | `current_user` |
| KEYS | [part7/keys.py:71](../part7/keys.py#L71) | `redactor` |
| CONV | [part7/model_convert.py:106](../part7/model_convert.py#L106) | `submit` |
| RUN | [part7/runner.py:127](../part7/runner.py#L127) | `run` |
| SUP | [tools/model-converter/supervisor.py:232](../tools/model-converter/supervisor.py#L232) | `Supervisor` |
| JAIL | [tools/model-converter/supervisor.py:110](../tools/model-converter/supervisor.py#L110) | `container_argv` |
| MMA | [part7/keys.py:93](../part7/keys.py#L93) | `part1_dotenv` |
| BT | [part7/parts/p5_analyse.py:84](../part7/parts/p5_analyse.py#L84) | `phrasing_args` |
