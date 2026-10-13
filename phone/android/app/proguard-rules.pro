# ONNX Runtime's native code finds its Java classes by name: R8 must not rename or drop them.
-keep class ai.onnxruntime.** { *; }
