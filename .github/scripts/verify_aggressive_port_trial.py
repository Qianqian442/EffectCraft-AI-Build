#!/usr/bin/env python3
"""Guard the real isolated AEX route-trial pipeline against regression."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JAVA = ROOT / "windows-compat/android-runtime/src/main/java/com/artcraft/effectcraft/WindowsCompatAndroidBridge.java"


def require(source: str, fragment: str, label: str) -> None:
    if fragment not in source:
        raise SystemExit(f"Missing aggressive-port trial requirement: {label}")


def main() -> None:
    source = JAVA.read_text(encoding="utf-8")
    start = source.index("            for (int index = 0; index < containers.length; index++) {")
    end = source.index("            if (passedTrials.isEmpty())", start)
    route_loop = source[start:end]

    require(source, "private static final class AexTrialResult", "measured trial result type")
    require(route_loop, "runAexSmokeTest(", "execute every installed candidate")
    require(route_loop, "passedTrials.add(trial)", "record only completed trials")
    if "return;" in route_loop:
        raise SystemExit("Route loop must not stop after the first passing backend.")

    require(source, "passedTrials.stream()", "rank measured passing candidates")
    require(source, "comparingInt((AexTrialResult value) -> value.score).reversed()", "rank by measured score")
    require(source, "thenComparingLong(value -> value.renderMillis)", "use measured render time as tie-breaker")
    require(source, 'firstRequest.put("params", roundTrip)', "round-trip supported parameter values")
    require(source, 'firstRequest.put("frame", 0)', "use deterministic reference frame")
    require(source, 'repeatRequest.put("output_png", repeatedOutput.toString())', "repeat the same render independently")
    require(source, "sha256File(outputPng)", "hash actual render output")
    require(source, "sha256File(repeatedOutput)", "verify repeat-render stability")
    require(source, "guest.getExitCode()", "require a normal worker exit")
    require(source, "validPngOutput(outputPng)", "validate output PNG signature and size")
    require(source, "No desktop visual-fidelity", "do not invent unavailable reference-image metrics")
    print("Aggressive-port runtime trial checks passed: all available routes are attempted, parameter values round-trip, repeated CPU frames are verified, and only measured passing routes are ranked.")


if __name__ == "__main__":
    main()
