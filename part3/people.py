"""`--all-people`: the files written for every tracked id (spec integration-contract.md "People").

`layout` turns the per-id results of `cli.process_all` into the relative paths and documents to write:
`person-<slug>/skeleton.json` (and the view's other files) per id, then `people.json`. Nothing here
touches the disk, so a failure on one id cannot leave a half-written folder.
"""

import re

SCHEMA_ID = "simon.part3.people/1"
SLUG = re.compile(r"[A-Za-z0-9_-]{1,40}")
INDEX_FILE = "people.json"
SKELETON_FILE = "skeleton.json"


def slugs(ids):
    """One folder-safe name per id: the id itself when it is `[A-Za-z0-9_-]{1,40}`, else `p<position>`.

    Positions count from 0 in first-seen order. A name already taken (compared without case, so a
    case-insensitive disk is safe) falls back to `p<position>`, then `p<position>-2` and so on.
    """
    taken, names = set(), []
    for position, pid in enumerate(ids):
        natural = str(pid) if SLUG.fullmatch(str(pid)) else None
        fallback = f"p{position}"
        options = [name for name in (natural, fallback) if name] + [f"{fallback}-{n}" for n in range(2, 1000)]
        name = next(option for option in options if option.lower() not in taken)
        taken.add(name.lower())
        names.append(name)
    return names


def layout(results, render_one):
    """[(relative path, document)] for `results` [(id, skeleton or {"skipped": reason})], `people.json` last.

    `render_one(skeleton)` gives {file name: document} for one person, the skeleton file first.
    """
    files, entries = [], []
    for (pid, skeleton), slug in zip(results, slugs([pid for pid, _ in results])):
        folder = f"person-{slug}"
        if "skipped" in skeleton:
            entries.append({"id": pid, "dir": folder, "frames_present": 0, "skipped": skeleton["skipped"]})
            continue
        files += [(f"{folder}/{name}", document) for name, document in render_one(skeleton).items()]
        entries.append({"id": pid, "dir": folder, "frames_present": skeleton["person"]["frames_present"],
                        "file": f"{folder}/{SKELETON_FILE}"})
    files.append((INDEX_FILE, {"schema": SCHEMA_ID, "people": entries}))
    return files
