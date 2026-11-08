"""Rogue Legend farming bot (see README.md)."""

import os

# numpy's OpenBLAS reserves a buffer per core on import (~490 MB committed with 16 cores). The bot does no
# matrix math (OCR runs in onnxruntime, images in OpenCV), so one thread: ~50 MB. Must run before numpy loads.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

__version__ = "1.10.0"
