"""Shared quality contract constants. Part 7 never decides measurement impact."""

QUALITY_FORMAT = "simon.quality.v1"
QUALITY_SCORE_CAP = 59
# Part 7's own fallback analysis was 1.4.0. This additive change is one minor step.
OWN_ANALYSIS_SCHEMA_VERSION = "1.5.0"

QUALITY_TIPS = {
    "dark": "The room was dark. Turn on a light in front of you, not behind you.",
    "backlit": "A bright light or window was behind you. Face the light, or put it beside the camera.",
    "overexposed": "The picture was washed out. Move out of direct sun or turn the lamp away from you.",
    "blurry": "The video was blurry. Prop the phone up, wipe the lens and add light.",
    "subject_small": "You were small in the frame. Move closer so you fill most of the height.",
    "body_cut_off": "Part of your body was out of frame. Step back until all of you fits.",
    "camera_moving": "The camera moved. Rest the phone on something steady.",
    "others_in_frame": "Someone else was in the frame and blocked you at times. Record with a clear space around you.",
    "tracking_unsteady": "The app lost track of you at times. Wear clothes that stand out from the background and keep the space around you clear.",
    "low_frame_rate": "The video was choppy. Close other apps and record in good light.",
    "joints_uncertain": "Your {joints} were hard to see. Make sure they are in view and well lit.",
}
