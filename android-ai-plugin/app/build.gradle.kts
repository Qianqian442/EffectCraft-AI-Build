plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.jetbrains.kotlin.android)
}

android {
    namespace = "com.artcraft.effectcraft.aiassistant"
    compileSdk = 36
    ndkVersion = "29.0.13113456"

    defaultConfig {
        applicationId = "com.artcraft.effectcraft.aiassistant"
        minSdk = 28
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"

        ndk {
            abiFilters += listOf("arm64-v8a")
        }
    }

    signingConfigs {
        create("release") {
            val keyPath = System.getenv("EFFECTCRAFT_KEYSTORE")
                ?: error("EFFECTCRAFT_KEYSTORE is required")
            val keyPassword = System.getenv("EFFECTCRAFT_KEY_PASSWORD")
                ?: error("EFFECTCRAFT_KEY_PASSWORD is required")
            storeFile = file(keyPath)
            storePassword = keyPassword
            keyAlias = "artcraftbuilder"
            this.keyPassword = keyPassword
            enableV1Signing = true
            enableV2Signing = true
            enableV3Signing = true
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlin {
        jvmToolchain(17)
        compileOptions {
            targetCompatibility = JavaVersion.VERSION_17
        }
    }

    packaging {
        jniLibs {
            useLegacyPackaging = false
        }
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    implementation(project(":lib"))
    implementation(libs.androidx.core.ktx)
    implementation(libs.kotlinx.coroutines.android)
}
