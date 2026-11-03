// Look inside a GLB before it is sent (docs/specs/model-picker.md "Before sending"): does it carry a skeleton? The
// server asks who an unrigged model shows before it makes one, so the dialog asks up front instead of after the upload.
// Reads only the 20-byte header and the JSON chunk, never the geometry. Resolves true, false, or null when the file is
// not a GLB or cannot be read (the server then decides).

const GLB_MAGIC = 0x46546c67; // "glTF", little endian
const JSON_CHUNK = 0x4e4f534a; // "JSON"
const HEADER_BYTES = 20;
export const MAX_JSON_BYTES = 16 * 1024 * 1024;

/** Pure: the answer for a glTF JSON document. */
export const jsonHasSkin = (doc) => !!doc && Array.isArray(doc.skins) && doc.skins.length > 0;

export async function glbHasSkin(file) {
  try {
    if (!file || typeof file.slice !== "function") return null;
    const head = new DataView(await file.slice(0, HEADER_BYTES).arrayBuffer());
    if (head.byteLength < HEADER_BYTES || head.getUint32(0, true) !== GLB_MAGIC || head.getUint32(16, true) !== JSON_CHUNK) return null;
    const length = head.getUint32(12, true);
    if (length <= 0 || length > MAX_JSON_BYTES) return null;
    return jsonHasSkin(JSON.parse(await file.slice(HEADER_BYTES, HEADER_BYTES + length).text()));
  } catch {
    return null;
  }
}
