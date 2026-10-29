# COCO val2017 one-person set: selection rule

Fixed before any scoring (TICKET-037, ADR-0004). No score chooses or changes it. `part2/coco_set.py` applies
it; its constants are this rule and `tests/test_coco_set.py` checks that they agree.

Source: `annotations/person_keypoints_val2017.json` in
<http://images.cocodataset.org/annotations/annotations_trainval2017.zip>
(sha256 `113a836d90195ee1f884e704da6304dfaaecff1f023f49b6ca93c4aaae470268`). Annotations: CC BY 4.0, COCO
Consortium.

## Rule

| # | Clause | Test on the annotations |
|---|---|---|
| 1 | Licence allows commercial use | the image's `license` id is one of 4, 5, 6, 7, 8 (table below) |
| 2 | One person | exactly one `person` annotation in the image, with `iscrowd` 0; an image with any crowd annotation is out |
| 3 | Whole body labelled | every keypoint has `v` 1 or 2 (none is 0) |
| 4 | Height measurable | the nose and both ankles have `v` 2 (visible) |
| 5 | Body size | nose to ankle-midpoint distance over the visible keypoints (the metric's body height) is at least 150 px |
| 6 | Order and count | images ordered by image id; the set is the first N = 20 |

Labels written to `labels_2d.json`: a visible keypoint (`v` 2) is copied as `[x, y]` exactly as COCO has it (no
offset, no rounding); an occluded one (`v` 1) is written as `null`, the labels' "not visible" as in the seated
set, and is not scored. COCO's keypoint names are the canonical names (both use the subject's left and
right), mapped by name. `frame` is the COCO image id.

## Why clauses 3 and 4 read as they do

The ticket asks for every keypoint labelled visible. Among the val2017 images that pass clauses 1 and 2,
17 have every keypoint visible, so that wording cannot give the set the spec requires. Clauses 3 and 4 keep
the whole body labelled and the body height exact, and they leave occluded joints out of the score as the
seated set does. This also admits side and turned views, which the operator ruling on #337 asks for (camera
angle must not matter).

The size floor and N were set from counts on the annotations, before any model ran on these images: 24
images pass clauses 1 to 4, and the floor in clause 5 keeps N of them. Counts, never scores.

## Licences: which allow commercial use

| id | Licence (COCO name) | URL | Commercial use | Why |
|---|---|---|---|---|
| 1 | Attribution-NonCommercial-ShareAlike License | <http://creativecommons.org/licenses/by-nc-sa/2.0/> | no | NonCommercial term |
| 2 | Attribution-NonCommercial License | <http://creativecommons.org/licenses/by-nc/2.0/> | no | NonCommercial term |
| 3 | Attribution-NonCommercial-NoDerivs License | <http://creativecommons.org/licenses/by-nc-nd/2.0/> | no | NonCommercial term |
| 4 | Attribution License | <http://creativecommons.org/licenses/by/2.0/> | yes | attribution is the only condition |
| 5 | Attribution-ShareAlike License | <http://creativecommons.org/licenses/by-sa/2.0/> | yes | ShareAlike binds adapted copies someone shares; it sets no limit on commercial use |
| 6 | Attribution-NoDerivs License | <http://creativecommons.org/licenses/by-nd/2.0/> | yes | NoDerivs forbids sharing adapted copies; commercial use of the unaltered image is allowed |
| 7 | No known copyright restrictions | <http://flickr.com/commons/usage/> | yes | Flickr Commons: the contributing institution knows of no copyright restriction |
| 8 | United States Government Work | <http://www.usa.gov/copyright.shtml> | yes | works of the US federal government carry no US copyright |

This repo never redistributes an image: the bytes stay in the local cache and only URLs and sha256 digests
are committed, so the ShareAlike and NoDerivs conditions are not triggered here. This table records the
reasoning behind the filter; it is not a legal opinion (ADR-0005). A licence URL outside this table stops the
fetch instead of being guessed.
