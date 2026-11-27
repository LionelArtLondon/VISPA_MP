"""Sequential, cancellable imports from explicitly selected Resolve projects."""

from vispa_mp.learning_data import import_timeline_reference, save_imported_reference
from vispa_mp.snapshot import normalize
from vispa_mp.timeline_identity import normalize_identity


def import_project_batch(client, entries, settings, cache, *, timeline_name="Personal Learning",
                         use_in_out=True, include_automatic=False, progress=None, cancel=None):
    if not isinstance(entries, list) or not entries or len(entries) > 2000:
        raise ValueError("Select between 1 and 2000 Resolve projects for the batch.")
    outcomes = []
    cancelled, stopped = False, ""
    for index, entry in enumerate(entries):
        if cancel is not None and cancel():
            cancelled = True
            break
        name = entry.get("name") or "Resolve project"

        def notify(value, state="Importing", fraction=0):
            if progress is None:
                return
            detail = str(value)
            if isinstance(value, dict):
                detail = " · ".join(str(value.get(key) or "") for key in ("label", "detail"))
                fraction = (int(value.get("step") or 1) - 1 + float(value.get("fraction") or 0)) / max(1, int(value.get("steps") or 1))
            progress({"step": index + 1, "steps": len(entries), "fraction": fraction,
                      "label": f"Chapter {index + 1}/{len(entries)}: {name}", "detail": detail,
                      "batch_row": index, "batch_state": state})

        notify("Opening the selected Resolve project and timeline…", "Opening")
        try:
            snapshot = normalize(client.request("learning_open", entry=entry, timeline_name=timeline_name))
            if (snapshot.get("project_name") != name or normalize_identity(snapshot.get("timeline_identity")) is None
                    or timeline_name and snapshot.get("timeline_name") != timeline_name):
                raise ValueError("Resolve returned a different project or timeline; this chapter was not imported.")
            if cancel is not None and cancel():
                raise InterruptedError("Batch import cancelled.")
            reference = import_timeline_reference(snapshot, settings, cache, name=name, use_in_out=use_in_out,
                                                   include_automatic=include_automatic, progress=notify, cancel=cancel)
            if cancel is not None and cancel():
                raise InterruptedError("Batch import cancelled.")
            save_imported_reference(reference)
            count = reference["summary"]["markers"]
            detail = f"Saved locally: {count} marked images"
            outcomes.append({"name": name, "status": "Saved", "detail": detail})
            notify(detail, "Saved", 1)
        except InterruptedError:
            cancelled = True
            outcomes.append({"name": name, "status": "Cancelled", "detail": "No reference saved for this operation."})
            notify("Cancelled before saving this reference.", "Cancelled")
            break
        except (OSError, ValueError, RuntimeError) as error:
            detail = str(error)
            outcomes.append({"name": name, "status": "Failed", "detail": detail})
            notify(detail, "Failed", 1)
            if isinstance(error, RuntimeError) and not detail.startswith("Learning import:"):
                stopped = detail
                break
    return {"outcomes": outcomes, "cancelled": cancelled, "stopped_error": stopped,
            "requested": len(entries), "saved": sum(item["status"] == "Saved" for item in outcomes)}
