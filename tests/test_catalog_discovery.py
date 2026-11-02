import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json

import pytest
from PySide6.QtWidgets import QApplication
from giftfinder.ui_common import application
from giftfinder.ui import MainWindow
from giftfinder.mobile_ui import MobileWindow
from giftfinder.qa import settle
from giftfinder.previews import asset_url


@pytest.mark.parametrize('window_class', [MainWindow, MobileWindow])
def test_myth_mask_can_be_found_on_main_catalog_with_an_old_profile(tmp_path, monkeypatch, window_class):
    monkeypatch.setenv('GIFT_FINDER_DATA_DIR', str(tmp_path))
    (tmp_path/'catalog-v2.json').write_text(json.dumps({'collections':['Easter Egg'],'backdrops':[],
        'traits':{'Easter Egg':{'models':[],'symbols':[]}}}), encoding='utf-8')
    app = QApplication.instance() or application()
    window = window_class(offline=True)
    window.show();settle(window)
    try:
        for query in ('маска', 'Mask', 'Myth Mask', 'mythmask'):
            window.catalog_search.setText(query);settle(window)
            assert [row['name'] for row in window.home_model.rows] == ['Myth Mask']
            assert window.home_grid.visualRect(window.home_model.index(0)).intersects(window.home_grid.viewport().rect())
            assert len(window.catalog.facets('Myth Mask')['models']) == 134
            assert window.assets.image(asset_url('collection','Myth Mask',size=256)) is not None
        window.catalog_search.clear()
        assert window.home_model.rowCount() >= 124
        assert window.filter_query.collection == ''
    finally:
        window.close();app.processEvents()
