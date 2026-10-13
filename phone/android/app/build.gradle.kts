plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.diego.roguebot_phone"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.diego.roguebot_phone"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = 30  // AccessibilityService.takeScreenshot (Android 11)
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    // The bot's templates and skill database come from the desktop bot (one source of truth).
    sourceSets["main"].assets.srcDir(file("build/botAssets"))

    buildTypes {
        release {
            // Signed with the debug key: the APK is installed by hand from the GitHub release.
            signingConfig = signingConfigs.getByName("debug")
            proguardFiles("proguard-rules.pro")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}

val copyBotAssets by tasks.registering(Copy::class) {
    from("../../../roguebot/templates") { into("templates") }
    from("../../../data/skills.json")
    into(file("build/botAssets"))
}
// The desktop bot's OCR models (rapidocr package) and their character list: python must have rapidocr.
val copyOcrModels by tasks.registering(Exec::class) {
    commandLine("python", file("../../tools/ocr_models.py").path, file("build/botAssets/ocr").path)
}
tasks.named("preBuild") { dependsOn(copyBotAssets, copyOcrModels) }

dependencies {
    implementation(project(":bot"))
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.22.0")
}
