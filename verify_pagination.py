import json
import sys
from pathlib import Path

from giftfinder.core import SearchQuery, norm
from giftfinder.providers import index_search, fragment_search, portals_search, SearchEngine

target = Path(sys.argv[1])
q = SearchQuery(collection='Easter Egg', markets=('fragment', 'portals'))
cached = index_search(q)
known = {norm(o.slug): o for o in cached.offers}
fr = fragment_search(q, known)
po = portals_search(q)
assert fr.cursors and po.cursors, 'No second page exposed by source'
class Catalog:
    pass
engine = SearchEngine(Catalog())
all_cursors = fr.cursors + po.cursors
page2 = engine.more(all_cursors, known)
assert not page2.warnings, 'Failed page request'
for market, first in (('fragment', fr), ('portals', po)):
    second = [o for o in page2.offers if o.market == market]
    assert second, f'No second-page offers for {market}'
    assert not ({o.key for o in first.offers} & {o.key for o in second}), f'Repeated first page for {market}'
report = {'fragment_page_1': len(fr.offers), 'portals_page_1': len(po.offers),
          'fragment_page_2': sum(o.market == 'fragment' for o in page2.offers),
          'portals_page_2': sum(o.market == 'portals' for o in page2.offers),
          'result': 'PASS: next pages differ from initial pages'}
(target / 'pagination.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report))
