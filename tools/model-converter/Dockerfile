# Simon model converter image (docs/specs/model-convert.md, ADR-0017).
# Headless Blender in a jail for FBX, .blend and gltf-zip uploads. Built by build.sh, run only by supervisor.py.
# The Blender tarball is pinned by sha256; a mismatch fails the build.
ARG BLENDER_SERIES=4.5
ARG BLENDER_VERSION=4.5.15
ARG BLENDER_SHA256=0d2b8bb2efe97e6c8eb57de6b7322f8800e1984e3125b60decca5f6771e4773e

FROM debian:bookworm-slim AS fetch
ARG BLENDER_SERIES
ARG BLENDER_VERSION
ARG BLENDER_SHA256
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl xz-utils \
 && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL -o /blender.tar.xz \
      "https://download.blender.org/release/Blender${BLENDER_SERIES}/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
 && echo "${BLENDER_SHA256}  /blender.tar.xz" | sha256sum -c - \
 && mkdir /blender \
 && tar -xJf /blender.tar.xz -C /blender --strip-components=1

FROM debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends libxi6 libxxf86vm1 libxfixes3 libxrender1 libgl1 libegl1 \
      libxkbcommon0 libsm6 libice6 libx11-6 libxext6 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=fetch /blender /opt/blender
COPY convert.py run.sh /opt/
RUN chmod 0755 /opt/run.sh && ln -s /opt/blender/blender /usr/local/bin/blender
USER 65534:65534
ENV HOME=/tmp
ENTRYPOINT ["/opt/run.sh"]
