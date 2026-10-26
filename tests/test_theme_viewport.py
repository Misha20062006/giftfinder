import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import pytest
from PySide6.QtWidgets import QApplication, QAbstractItemView
from giftfinder.ui import MainWindow
from giftfinder.ui_common import application


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or application()


@pytest.mark.parametrize('size', [(1050,740), (1400,900)])
def test_expanded_theme_viewport_preserves_a_full_catalog_row_and_scrolls_to_every_theme(app, tmp_path, monkeypatch, size):
    monkeypatch.setenv('GIFT_FINDER_DATA_DIR', str(tmp_path / 'profile'))
    window = MainWindow(offline=True)
    collapsed = window.themes_collapsed
    stored = window.store.data['settings'].get('themes_collapsed')
    window.resize(*size); window.show()
    for _ in range(3): app.processEvents()
    window.theme_grid.doItemsLayout(); app.processEvents()
    assert window.theme_model.rowCount() == len(window.catalog.themes) >= 20
    assert (window.width(), window.height()) == size
    assert window.home_grid.viewport().height() >= window.home_grid.gridSize().height()
    assert window.theme_grid.verticalScrollBar().maximum() > 0
    assert window.theme_grid.horizontalScrollBar().maximum() == 0
    for row in range(window.theme_model.rowCount()):
        index = window.theme_model.index(row)
        window.theme_grid.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        app.processEvents()
        assert window.theme_grid.viewport().rect().contains(window.theme_grid.visualRect(index)), row
    assert window.themes_collapsed == collapsed
    assert window.store.data['settings'].get('themes_collapsed') == stored
    window.close(); app.processEvents()
