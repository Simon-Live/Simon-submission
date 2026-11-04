# Open-source notices

Simon is released under the MIT licence. It uses the open-source software, fonts, AI models and stock video below,
each under its own licence. The licence texts for three.js, Mermaid, idna and Sniglet follow the tables. Inter's is `web/vendor/inter/LICENSE` and Mermaid's is also `web/vendor/mermaid/LICENSE`. The SAM License and the Apache License 2.0 text for the 3D demo data are `web/mesh-demo/LICENSE-SAM.txt` and `web/mesh-demo/LICENSE-MHR-Apache-2.0.txt`. The Apache License 2.0, the Mozilla Public License 2.0, the SAM License and the Meta Model API Terms of Service are at the addresses at the end of this file.

## Software and fonts in the web app

| Component | Used for | Licence |
|---|---|---|
| three.js 0.170.0, with its add-ons OrbitControls.js, GLTFLoader.js, BufferGeometryUtils.js and SkeletonUtils.js | The 3D views of the original and of you | MIT |
| Mermaid 11.17.2, with lodash-es, DOMPurify 3.4.12 and Cytoscape.js bundled | Diagrams | MIT; DOMPurify under Apache License 2.0 or Mozilla Public License 2.0. The file bundles its dependencies. As npm lists them: MIT for most of them (among them khroma, cytoscape, dagre-d3-es, marked, katex, roughjs, dayjs, stylis, uuid, es-toolkit, `@braintree/sanitize-url` and `@mermaid-js/parser`), ISC for d3, BSD-3-Clause for d3-sankey and Apache-2.0 for chevrotain. |
| Inter 4 font | The app's text | SIL Open Font License 1.1, copyright 2016 The Inter Project Authors |
| Sniglet font | The "simon" logo, the grade and the score | SIL Open Font License 1.1 |
| MediaPipe Tasks Vision 0.10.14 (Google), with the Pose Landmarker Lite model | Live check, only when you turn it on | Apache License 2.0 |

## Software on the server

| Component | Used for | Licence |
|---|---|---|
| idna 3.20 | Sign-in email addresses in any language | BSD 3-Clause |
| Blender 4.5 LTS and 3.6 LTS | Reading uploaded 3D files (FBX, .blend, glTF) | GPL-2.0-or-later |
| FBX2glTF 0.9.7 | Reading older FBX files | BSD 3-Clause; contains Autodesk FBX code under Autodesk's notice, below |

## AI models

| Model | Used for | Licence or terms |
|---|---|---|
| SAM 3.1 (Meta) | Following the person in a trainer's recording, only when that trainer ticks the Meta box | Meta Model API Terms of Service |
| SAM 3D Body (Meta) | The 3D body in each frame | SAM License (19 November 2025) |
| MHR, Momentum Human Rig (Meta) | The body model and the rig of a 3D avatar | Apache License 2.0, and the SAM License for the copy that comes with SAM 3D Body |
| SAM 3D Objects (Meta) | A 3D model from one picture | SAM License (19 November 2025) |
| Muse Spark (Meta) | Naming a movement's phases, explaining your history, a second opinion | Meta Model API Terms of Service |
| Muse Spark Open (Meta), hosted on Baseten | Writing each difference as one sentence | Its model licence and Baseten's terms |
| Muse Glimmer (Meta) | The same sentences in private mode; off on simon.live | Its model licence |
| Muse Wonder (Meta) | Answering a question about one of your takes | Meta Model API Terms of Service |
| Muse Image (Meta) | Your own frame redrawn in the matching pose; off on simon.live | Meta Model API Terms of Service |
| Muse Voice Transcribe (Meta) | Writing down a creator's spoken cues; off on simon.live, where faster-whisper does this | Meta Model API Terms of Service |
| Meta MMS-TTS voices | Reading feedback aloud; not used on simon.live | CC BY-NC 4.0 (non-commercial) |
| SAM 2.1 (Meta) | Following the people in each frame | Apache License 2.0 |
| YOLOX, through rtmlib | Finding the people in each frame | Apache License 2.0 |
| faster-whisper | Writing down a creator's spoken cues | MIT |
| TRELLIS (Microsoft) | A fallback for SAM 3D Objects | MIT |
| MoGe-2 (Microsoft) | The camera's field of view | MIT, with Apache License 2.0 for its DINOv2 code |

## Stock video

| Source | Used for | Licence |
|---|---|---|
| Pexels stock clips | Example movements and demo material | Pexels License (https://www.pexels.com/license/) |
| 3D demo data made with SAM 3D Body from two Pexels clips | The 3D demo | SAM License and Apache License 2.0, whose texts come with the data |

## FBX2glTF and the Autodesk FBX notice

The package's `LICENSE` and `README.md` are the only licence files it ships, and they name two things:

> Copyright (c) Facebook, Inc. and its affiliates. All rights reserved. 3-clause BSD license, as in the package's `LICENSE`.

> This software contains Autodesk® FBX® code developed by Autodesk, Inc. Copyright 2017 Autodesk, Inc. All rights, reserved. Such code is provided "as is" and Autodesk, Inc. disclaims any and all warranties, whether express or implied, including without limitation the implied warranties of merchantability, fitness for a particular purpose or non-infringement of third party rights. In no event shall Autodesk, Inc. be liable for any direct, indirect, incidental, special, exemplary, or consequential damages (including, but not limited to, procurement of substitute goods or services; loss of use, data, or profits; or business interruption) however caused and on any theory of liability, whether in contract, strict liability, or tort (including negligence or otherwise) arising in any way out of such code.

The package carries no notice for anything else. A search of the binary's strings on 2026-11-04 also finds these, none with a licence text in the package: Draco, nlohmann json, fifo_map, mathfu, cppcodec, CLI11, stb_image, Boost, libxml2, zlib 1.2.11 (copyright Jean-loup Gailly and Mark Adler), libiconv, and a copyright line of Oculus VR, LLC (2016-2018). The Modal image keeps the package's `LICENSE` at `/opt/fbx2gltf/LICENSE`. The binary runs only inside the converter's sandbox and is not given to anyone.

## Licence texts

### three.js (MIT)

```
The MIT License

Copyright © 2010-2024 three.js authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

### Mermaid (MIT)

```
The MIT License (MIT)

Copyright (c) 2014 - 2022 Knut Sveidqvist

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### idna (BSD 3-Clause)

```
BSD 3-Clause License

Copyright (c) 2013-2026, Kim Davies and contributors.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

### Sniglet (SIL Open Font License 1.1)

```
Copyright (c) 2008, Haley Fiege (haley@kingdomofawesome.com), Copyright (c) 2012, Brenda Gallo (gbrenda1987@gmail.com), Copyright (c) 2013, Pablo Impallari (www.impallari.com|impallari@gmail.com)

This Font Software is licensed under the SIL Open Font License, Version 1.1.
This license is copied below, and is also available with a FAQ at:
http://scripts.sil.org/OFL


-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded, 
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
```

The full texts of the Apache License 2.0 (https://www.apache.org/licenses/LICENSE-2.0), the Mozilla Public License 2.0 (https://www.mozilla.org/MPL/2.0/), the SAM License (https://github.com/facebookresearch/sam-3d-body/blob/main/LICENSE) and the Meta Model API Terms of Service (https://dev.meta.ai/legal/terms-of-service) are at those addresses.

Meta, SAM and Muse are trademarks of Meta Platforms, Inc. Simon is an independent project and is not endorsed by Meta.
