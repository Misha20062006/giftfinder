# Android surface lifecycle backport

Android 0.8.0 rebuilds the Qt 6.12.0 platform plugin and `Qt6Android.jar` together.
The surface lifecycle comes from upstream commit
[`f31445f99717c06cbca904d752d9fe47e88ca338`](https://github.com/qt/qtbase/commit/f31445f99717c06cbca904d752d9fe47e88ca338).
The user approved this change after repeated native failures in `eglSurface()`
while Android accessibility held the UI-thread deadlock protector.

`surface-lifecycle.patch` applies to the pinned Qt 6.12.0 archive. It includes
the upstream background-priming and obsolete surface-lock cleanup prerequisites.
It preserves Qt 6.12.0's system UI handling/JNI registration and the existing
three-argument `QtInputDelegate.longPress` ABI. Those unrelated upstream changes
require other Java classes and are deliberately excluded from this backport.
Original, upstream and adapted source hashes are recorded in
`mobile/android-build-inputs.json`. The existing accessibility-guard backport
is applied separately to `androidjniaccessibility.cpp`.

`tools/android_qt_platform.py` checks the original hashes, applies the exact
patch and validates all fourteen outputs. It rebuilds the native plugin against
the same-version SDK and the Core/Gui libraries from the pinned PySide wheel.
The four changed Java sources are compiled for Java 8 against Android API 35 and
the wheel's original Java archives. Complete class families are replaced,
including obsolete anonymous inner classes; other Qt APIs remain from 6.12.0.

The rebuilt JAR is selected in Buildozer and installed in the Python copies.
Verification checks every packaged plugin/JAR copy and the actual native JNI
declarations in `classes*.dex`. A cached or mismatched Java/native combination
fails the build. The patch, build code and source pins change the compatibility
fingerprint used for native compilation.

The upstream LGPL/GPL terms apply to this patch and its source. See
`THIRD_PARTY_NOTICES.txt` and the Qt licenses in `third-party/`. The source
archive, build inputs and patch permit rebuilding with replacement Qt code.
