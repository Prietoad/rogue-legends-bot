"""Copy the desktop bot's OCR models (the rapidocr package) for the phone app: the detection and recognition
ONNX files, plus the recognition model's character list as JSON (read exactly like rapidocr reads it).
  python phone/tools/ocr_models.py OUT_DIR
"""
import json
import shutil
import sys
from pathlib import Path

import onnxruntime as ort
import rapidocr

MODELS = Path(rapidocr.__file__).parent / "models"
DET, REC = "PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx"

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for name in (DET, REC):
    if not (out / name).exists() or (out / name).stat().st_size != (MODELS / name).stat().st_size:
        shutil.copyfile(MODELS / name, out / name)
meta = ort.InferenceSession(str(MODELS / REC)).get_modelmeta().custom_metadata_map
(out / "rec_characters.json").write_text(json.dumps(meta["character"].splitlines(), ensure_ascii=False), encoding="utf-8")
print(out)
