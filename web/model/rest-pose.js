// TICKET-389: the still standing pose the model preview falls back to when there is no example movement (prod answers
// `api/fixture-result` 404). Same 17-joint layout and metres as a replay (frame 0 of the committed example result), so
// every model is posed on the same skeleton and can be turned by dragging.
export const REST_FPS = 30;
export const REST_JOINTS = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"];
export const REST_BONES = [[0, 1], [0, 2], [1, 3], [2, 4], [0, 5], [0, 6], [5, 6], [11, 12], [5, 11], [6, 12], [5, 7], [7, 9], [6, 8], [8, 10], [11, 13], [13, 15], [12, 14], [14, 16]];
export const REST_POSE = [[0, 0.675, 0.043], [0.047, 0.712, 0.06], [-0.047, 0.712, 0.06], [0.116, 0.697, 0.029], [-0.116, 0.697, 0.029],
  [0.198, 0.49, 0], [-0.198, 0.49, 0], [0.198, 0.173, 0], [-0.198, 0.173, 0], [0.198, -0.075, 0], [-0.198, -0.075, 0],
  [0.125, 0, 0], [-0.125, 0, 0], [0.125, -0.416, 0], [-0.125, -0.416, 0], [0.125, -0.835, 0], [-0.125, -0.835, 0]];

/** A replay-shaped object of two identical frames, for `normalizeReplay`. */
export function restReplay() {
  const frame = () => REST_POSE.map((p) => [...p]);
  return { fps: REST_FPS, joints: REST_JOINTS, bones: REST_BONES, expected: [frame(), frame()], follower: [frame(), frame()], exp_to_fol: [0, 1] };
}
