// Glue of the trainer's "Home programme" form (docs/specs/progress-sheet.md, TICKET-283): the teacher page mounts it for the
// entry's own author. It reads the measure list and the entry's programme, and saves with `PUT api/programmes/<entry>`
// (JSON, same origin, as share does). The server answers 404 to anyone but the owner, so the attribution check here only
// keeps the form off other people's screens.
import { ensureCss } from "./ui.js";
import { call } from "./me-api.js";
import * as model from "./model/programme.js";
import { programmeForm } from "./views/programme-form.js";

/** Add the form to `screen` when `attribution` says the viewer is the author; nothing otherwise. */
export async function mountProgrammeForm(screen, entryId, attribution) {
  if (!model.showsForm(attribution)) return null;
  const [list, current] = await Promise.all([
    call("GET", model.listUrl),
    call("GET", model.entryUrl(entryId), undefined, { expectStatus: [404] }), // no programme yet is a normal answer
  ]);
  if (list.status !== 200) return null;
  ensureCss("theme/progress-sheet.css", "data-progress-sheet-css");
  const vm = { ...model.formModel(list.body, current.status === 200 ? current.body : null), canSave: model.canSave };
  const save = async (measure) => { // "Not set" clears with DELETE, a measure saves with PUT (model.saveRequest)
    const req = model.saveRequest(entryId, measure);
    const res = await call(req.method, req.url, req.body, { expectStatus: [400, 401, 404] });
    return model.saveResult(res.status, res.body);
  };
  const form = programmeForm(model.TEXT, vm, save);
  screen.append(form);
  return form;
}
