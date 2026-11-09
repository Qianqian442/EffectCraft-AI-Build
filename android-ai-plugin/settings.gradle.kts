pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "EffectCraftDeepSeekPlugin"
include(":app", ":lib")
project(":lib").projectDir = file("../llama.cpp/examples/llama.android/lib")
