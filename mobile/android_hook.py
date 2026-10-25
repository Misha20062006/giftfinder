"""Small compatibility fix for Qt's pinned python-for-android bootstrap.

Android 9-15 extracts release native libraries only when named lib*.so. The
upstream Qt template preloads QtCore.abi3.so etc without that required prefix.
Keep the same libraries and loading order, but give their installer entries a
valid name. Python's package files keep their normal extension-module names.
"""
from pathlib import Path
import re
import xml.etree.ElementTree as ET


LEGACY_KEY_HANDLER = '''    long lastBackClick = SystemClock.elapsedRealtime();

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        // If it wasn't the Back key or there's no web page history, bubble up to the default
        // system behavior (probably exit the activity)
        if (SystemClock.elapsedRealtime() - lastBackClick > 2000) {
            lastBackClick = SystemClock.elapsedRealtime();
            Toast.makeText(this, "Click again to close the app", Toast.LENGTH_LONG).show();
            return true;
        }

        lastBackClick = SystemClock.elapsedRealtime();
        return super.onKeyDown(keyCode, event);
    }'''
QT_KEY_HANDLER = '''    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        return super.onKeyDown(keyCode, event);
    }'''
LEGACY_RESULT_PREFIX = '''    protected void onActivityResult(int requestCode, int resultCode, Intent intent) {
        if (this.activityResultListeners == null) return;'''
QT_RESULT_PREFIX = '''    protected void onActivityResult(int requestCode, int resultCode, Intent intent) {
        super.onActivityResult(requestCode, resultCode, intent);
        if (this.activityResultListeners == null) return;'''


def fix_qt_activity_delegation(distribution):
    """Restore Qt key and file-picker callbacks, preserving p4a's Java listeners.

    Match only the two exact methods in pinned p4a 58d21141. A changed upstream
    implementation needs review instead of a broad Java source rewrite.
    """
    path = Path(distribution) / 'src/main/java/org/kivy/android/PythonActivity.java'
    source = path.read_text(encoding='utf-8')
    for original, replacement in ((LEGACY_KEY_HANDLER, QT_KEY_HANDLER),
                                  (LEGACY_RESULT_PREFIX, QT_RESULT_PREFIX)):
        if source.count(original) == 1:
            source = source.replace(original, replacement, 1)
        elif original not in source and source.count(replacement) == 1:
            continue
        else:
            raise RuntimeError('Pinned Qt PythonActivity callback changed; review the bootstrap compatibility patch')
    path.write_text(source, encoding='utf-8')


def fix_binding_library_names(distribution):
    distribution = Path(distribution)
    path = distribution / 'src/main/res/values/libs.xml'
    tree = ET.parse(path)
    changed = []
    for array in tree.getroot().findall("array[@name='load_local_libs']"):
        for item in array.findall('item'):
            match = re.fullmatch(r'([^;]+);(Qt\w+\.abi3\.so)', item.text or '')
            if not match:
                continue
            architecture, filename = match.groups()
            if architecture not in {'arm64-v8a', 'x86_64'}:
                raise RuntimeError('Unknown Qt binding preload architecture')
            library = distribution / 'libs' / architecture / filename
            installable = library.with_name('lib' + filename)
            if library.is_file():
                library.replace(installable)
            elif not installable.is_file():
                raise RuntimeError(f'Qt binding preload library is missing: {filename}')
            item.text = architecture + ';' + installable.name
            changed.append(installable.name)
    tree.write(path, encoding='utf-8', xml_declaration=True)
    return changed


def after_apk_build(toolchain):
    """Runs after p4a renders resources and before Gradle packages/signs the APK."""
    changed = fix_binding_library_names(toolchain._dist.dist_dir)
    fix_qt_activity_delegation(toolchain._dist.dist_dir)
    print('GiftFinder: installable Qt binding library names:', ', '.join(changed), flush=True)
