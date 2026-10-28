"""View `native`: Part 3's own `simon.skeleton/1` file, unchanged."""

from part3 import views

NAME = "native"
DESCRIPTION = "Part 3's own skeleton.json (simon.skeleton/1), with the body and input.adapters blocks"
SCHEMA = "skeleton.schema.json"


def render(skeleton, **opts):
    views.reject_options(opts, NAME)
    return skeleton
