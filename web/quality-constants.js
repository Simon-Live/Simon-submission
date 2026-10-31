// Browser advice only. Signal strength never determines a score or major/minor impact here.
// Keep every pre-record measurement threshold together; log them with each take for calibration.
export const PRERECORD_THRESHOLDS = Object.freeze({
  width: 160,
  height: 90,
  sample_ms: 500,
  clear_ms: 2000,
  max_tips: 2,
  border_fraction: 0.15,
  dark_luma: 70,
  backlit_difference: 50,
  backlit_center_luma_max: 100,
  clipped_luma: 250,
  clipped_share: 0.10,
  blurry_laplacian_variance: 12,
  blurry_min_contrast: 16,
  blurry_min_luma: 45,
  camera_border_difference: 0.10,
  border_edge_gradient: 70,
  busy_border_edge_density: 0.30,
});

export const QUALITY_TIPS = Object.freeze({
  dark: "The room was dark. Turn on a light in front of you, not behind you.",
  backlit: "A bright light or window was behind you. Face the light, or put it beside the camera.",
  overexposed: "The picture was washed out. Move out of direct sun or turn the lamp away from you.",
  blurry: "The video was blurry. Prop the phone up, wipe the lens and add light.",
  subject_small: "You were small in the frame. Move closer so you fill most of the height.",
  body_cut_off: "Part of your body was out of frame. Step back until all of you fits.",
  camera_moving: "The camera moved. Rest the phone on something steady.",
  others_in_frame: "Someone else was in the frame and blocked you at times. Record with a clear space around you.",
  tracking_unsteady: "The app lost track of you at times. Wear clothes that stand out from the background and keep the space around you clear.",
  low_frame_rate: "The video was choppy. Close other apps and record in good light.",
  joints_uncertain: "Your {joints} were hard to see. Make sure they are in view and well lit.",
  busy_background: "A busy background can confuse tracking. A plain wall behind you works best.",
});

export const PRERECORD_CODES = Object.freeze([
  "dark", "backlit", "overexposed", "camera_moving", "blurry", "busy_background",
]);
