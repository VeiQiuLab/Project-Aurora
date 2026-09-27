"""Read-only model inventory through the externally supplied Cubism Core ABI.

No SDK/model copy or asset repair. JSON output contains metadata, not model data.
"""
import argparse
import ctypes as c
import hashlib
import json
from pathlib import Path


def audit(model_file, core_dll):
    model_file = Path(model_file).resolve(strict=True)
    root = model_file.parent
    metadata = json.loads(model_file.read_text(encoding="utf-8-sig"))
    refs = metadata["FileReferences"]
    assets = []

    def asset(name):
        path = (root / name).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError("Asset outside model directory")
        raw = path.read_bytes()
        assets.append(dict(file=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        return raw

    moc_bytes = asset(refs["Moc"])
    for name in refs.get("Textures", []):
        asset(name)
    for key in ("Physics", "Pose", "DisplayInfo", "UserData"):
        if refs.get(key):
            asset(refs[key])
    motions = {}
    for group, entries in refs.get("Motions", {}).items():
        motions[group] = []
        for entry in entries:
            motion = json.loads(asset(entry["File"]))
            motions[group].append(dict(file=entry["File"], meta=motion["Meta"], curves=motion.get("Curves", [])))
            if entry.get("Sound"):
                asset(entry["Sound"])
    expressions = []
    for entry in refs.get("Expressions", []):
        expressions.append(dict(name=entry["Name"], data=json.loads(asset(entry["File"]))))
    core = c.CDLL(str(Path(core_dll).resolve(strict=True)))

    def function(name, result, args):
        fn = getattr(core, name)
        fn.restype, fn.argtypes = result, args
        return fn

    def aligned(size, alignment):
        backing = c.create_string_buffer(size + alignment)
        return backing, (c.addressof(backing) + alignment - 1) & ~(alignment - 1)

    # Core requires 64-byte moc alignment, 16-byte model alignment; buffers live
    # through all ABI calls. Revive modifies memory only, never the source file.
    moc_storage, moc_address = aligned(len(moc_bytes), 64)
    c.memmove(moc_address, moc_bytes, len(moc_bytes))
    moc = function("csmReviveMocInPlace", c.c_void_p, [c.c_void_p, c.c_uint])(moc_address, len(moc_bytes))
    if not moc:
        raise ValueError("Invalid moc")
    size = function("csmGetSizeofModel", c.c_uint, [c.c_void_p])(moc)
    model_storage, model_address = aligned(size, 16)
    model = function("csmInitializeModelInPlace", c.c_void_p, [c.c_void_p, c.c_void_p, c.c_uint])(moc, model_address, size)
    if not model:
        raise ValueError("Model initialization failed")
    count = function("csmGetParameterCount", c.c_int, [c.c_void_p])(model)
    ids = function("csmGetParameterIds", c.POINTER(c.c_char_p), [c.c_void_p])(model)
    arrays = [function("csmGetParameter" + name + "Values", c.POINTER(c.c_float), [c.c_void_p])(model)
              for name in ("Minimum", "Maximum", "Default")]
    params = [dict(id=ids[i].decode(), minimum=arrays[0][i], maximum=arrays[1][i], default=arrays[2][i]) for i in range(count)]
    mouth_geometry = None
    mouth_index = next((i for i, p in enumerate(params) if p["id"] == "ParamMouthOpenY"), None)
    if mouth_index is not None:
        values = function("csmGetParameterValues", c.POINTER(c.c_float), [c.c_void_p])(model)
        update = function("csmUpdateModel", None, [c.c_void_p])
        drawable_count = function("csmGetDrawableCount", c.c_int, [c.c_void_p])(model)
        counts = function("csmGetDrawableVertexCounts", c.POINTER(c.c_int), [c.c_void_p])(model)
        positions = function("csmGetDrawableVertexPositions", c.POINTER(c.POINTER(c.c_float)), [c.c_void_p])
        samples = []
        for value in (arrays[0][mouth_index], arrays[1][mouth_index]):
            values[mouth_index] = value
            update(model)
            points = positions(model)
            samples.append([points[d][j] for d in range(drawable_count) for j in range(counts[d] * 2)])
        mouth_geometry = max(abs(a-b) for a, b in zip(*samples))
    return dict(model=str(model_file), assets=assets, parameters=params, motions=motions,
                expressions=expressions, groups=metadata.get("Groups", []),
                physics=refs.get("Physics"), pose=refs.get("Pose"), mouth_vertex_max_delta=mouth_geometry)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--core-dll", required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.model, args.core_dll), ensure_ascii=False, indent=2))
