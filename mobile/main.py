"""Android entry point; desktop app.py remains a separate desktop application."""
import os
from pathlib import Path
import sys

source_root = Path(__file__).resolve().parent.parent
if (source_root / 'giftfinder').is_dir():
    sys.path.insert(0, str(source_root))

def main():
    from PySide6.QtCore import QTimer
    from giftfinder.mobile_ui import MobileWindow
    from giftfinder.ui_common import application

    app = application()
    window = MobileWindow(offline=os.environ.get('GIFT_FINDER_ANDROID_SMOKE') == '1')
    window.show()
    QTimer.singleShot(250, lambda: print('GIFTFINDER_ANDROID_READY', flush=True))
    return app.exec()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        from giftfinder.platform_support import data_directory
        directory = data_directory(); directory.mkdir(parents=True, exist_ok=True)
        (directory / 'startup-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        traceback.print_exc()
        raise SystemExit(1)
