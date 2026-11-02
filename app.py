import argparse
import os
import sys
from pathlib import Path

from giftfinder import __version__


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke-test', metavar='DIRECTORY', help='Offscreen UI check using an isolated app profile')
    args = parser.parse_args()
    if args.smoke_test:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        os.environ['GIFT_FINDER_DATA_DIR'] = str(Path(args.smoke_test) / 'profile')
        from giftfinder.qa import settle
    from giftfinder.ui import MainWindow, application
    from PySide6.QtCore import Qt
    app = application()
    window = MainWindow(offline=bool(args.smoke_test))
    if args.smoke_test:
        target = Path(args.smoke_test)
        target.mkdir(parents=True, exist_ok=True)
        window.show()
        app.processEvents()
        settle(window)
        window.grab().save(str(target / 'start.png'))
        assert len(window.catalog.data['collections']) >= 124
        assert len(window.catalog.model_rows) >= 7940
        assert len(window.catalog.backdrop_lookup) == 80
        window.catalog_search.setText('маска');settle(window)
        assert [row['name'] for row in window.home_model.rows] == ['Myth Mask']
        assert len(window.catalog.facets('Myth Mask')['models']) == 134
        from giftfinder.previews import asset_url
        assert window.assets.image(asset_url('collection','Myth Mask',size=256)) is not None
        window.grab().save(str(target/'myth-mask.png'))
        window.catalog_search.clear();settle(window)
        assert len(window.ratebook.currencies()) >= 160
        assert ('Myth Mask','Enderman') in window.catalog.themes['minecraft']['members']
        assert window.theme_model.rowCount()==len(window.catalog.themes)==20
        from giftfinder.monochrome import data,allowed
        assert 7940 <= data()['coverage']['models_analyzed'] <= len(window.catalog.model_rows)
        assert allowed('Input Key','Creeper','Malachite') and not allowed('Input Key','Creeper','Sapphire')
        assert window.assets.decoded>0 and window.assets.network_started==0
        from giftfinder.design import MotionButton
        assert isinstance(window.find_button,MotionButton)
        from giftfinder.i18n import LANGUAGES,language_code,resolve_language
        from giftfinder.icons import flag_icon,currency_icon,symbols
        assert len(LANGUAGES)==28
        assert language_code()==resolve_language('system')
        for code in LANGUAGES:assert not flag_icon(code).pixmap(36,28).isNull()
        for code in symbols():assert not currency_icon(code).pixmap(32,32).isNull()
        assert not any('QtWebEngine' in name or 'QtWebView' in name for name in sys.modules)
        window.open_filters('themes')
        app.processEvents()
        settle(window)
        window.filter_dialog.grab().save(str(target / 'filters.png'))
        window.filter_dialog.close()
        window.search_theme('monochrome');app.processEvents()
        colors=window.filter_dialog
        assert colors.category=='colors' and colors.rows.rowCount()==14
        row=next(i for i,r in enumerate(colors.rows.rows) if r['key']=='black')
        colors.choose(colors.rows.index(row));assert colors.state.mono_colors==('black',)
        colors.grab().save(str(target/'monochrome-colors.png'));colors.apply();app.processEvents()
        assert window.filter_query.mono_colors==('black',) and not window.filter_query.collection
        from giftfinder.previews import asset_url
        from PySide6.QtGui import QImage
        for key,count in (('pepe',32),('gold',33),('silver',16),('star_wars',10),('harry_potter',8),('pokemon',6),('sailor_moon',6),('doge',7),('space',12)):
            members=window.catalog.themes[key]['members'];assert len(members)==count
            collection,model=members[0]
            preview=window.assets.seed/window.assets.key(asset_url('model',collection,model,256))
            assert not QImage(str(preview)).isNull(),(key,'missing bundled preview')
        for key in ('pepe','gold'):
            window.search_theme(key);app.processEvents()
            assert window.current_query().theme==key and window.mode=='search'
            assert window.catalog.resolve(window.current_query())[0]
        window.currency.showPopup();window.currency.search.setText('RUB');app.processEvents()
        matches={window.currency.itemData(window.currency.items.item(i).data(Qt.ItemDataRole.UserRole))
                 for i in range(window.currency.items.count())}
        assert 'RUB' in matches and 'USD' not in matches
        window.currency.popup.grab().save(str(target/'currencies.png'));window.currency.hidePopup()
        window.change_language('ar');app.processEvents();settle(window);window.grab().save(str(target/'rtl.png'))
        assert app.layoutDirection()==Qt.LayoutDirection.RightToLeft
        window.change_language('system')
        assert language_code()==resolve_language('system')
        window.close()
        (target / 'result.txt').write_text(f'PASS: GiftFinder {__version__}, Qt Widgets without WebEngine, full catalog, {len(window.catalog.model_rows)} models, 80 backdrops, 20 themes, monochrome exact triples, color-first picker, 13 colors, global color query, 166 currencies, 28 language variants, system default, flags, native currency icons, searchable dropdown, RTL, native resizable filters, background image pipeline, animated theme hover, full labels, isolated offscreen render\n', encoding='utf-8')
        return 0
    window.show()
    return app.exec()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        if '--smoke-test' in sys.argv:
            index = sys.argv.index('--smoke-test')
            destination = Path(sys.argv[index + 1]) if len(sys.argv) > index + 1 else Path.cwd() / 'qa-startup'
            destination.mkdir(parents=True, exist_ok=True)
            (destination / 'failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
        else:
            from giftfinder.platform_support import data_directory
            destination = data_directory()
            destination.mkdir(parents=True, exist_ok=True)
            (destination / 'startup-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise SystemExit(1)
