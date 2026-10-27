// The bot engine: a port of the desktop bot (roguebot/) in plain Kotlin, without Android, so its
// tests run on the PC against the same screenshots (tests/fixtures).
plugins {
    id("org.jetbrains.kotlin.jvm")
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

dependencies {
    compileOnly("org.json:json:20240303")  // Android has org.json built in
    compileOnly("com.microsoft.onnxruntime:onnxruntime:1.22.0")  // the app brings onnxruntime-android (same API)
    testImplementation("com.microsoft.onnxruntime:onnxruntime:1.22.0")
    testImplementation("org.json:json:20240303")
    testImplementation("junit:junit:4.13.2")
}

tasks.test {
    workingDir = projectDir  // Fixtures.ROOT is relative to it
    maxHeapSize = "2g"
    // Test classes in parallel JVMs: ParityTest and OcrParityTest each walk every fixture (the parsers share a
    // global language, so they can't use threads inside one JVM); phone OCR reads are shared via build/ocr_cache.
    maxParallelForks = 3
    testLogging { events("failed"); exceptionFormat = org.gradle.api.tasks.testing.logging.TestExceptionFormat.FULL }
}
