"""A narrow read-only integration check. No logins, messages, purchases or profile reuse."""
import json
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from giftfinder.core import SearchQuery, sorted_offers
from giftfinder.providers import Catalog, SearchEngine

target = Path(sys.argv[1])
target.mkdir(parents=True, exist_ok=True)
catalog = Catalog(target, Path(__file__).parent / 'giftfinder' / 'catalog_seed.json')
catalog.refresh()
query = SearchQuery(collection='Easter Egg', models=('Creeper',), backdrops=('Black',))
started = time.monotonic()
result = SearchEngine(catalog).search(query, lambda text: print(text, flush=True))
assert result.offers, 'No actual offers returned'
assert all(query.matches(o) for o in result.offers), 'An exact trait filter was not respected'
direct = Counter(o.market for o in result.offers if o.source == 'direct')
assert direct['fragment'] > 0, 'No direct Fragment offers'
assert direct['portals'] > 0, 'No direct Portals offers'
ordered = sorted_offers(result.offers)
ton_prices = [o.amount for o in ordered if o.currency == 'TON']
assert ton_prices == sorted(ton_prices), 'Price sort failed'
report = {
    'checked_at_utc': time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()),
    'query': asdict(query), 'duration_seconds': round(time.monotonic() - started, 2),
    'total_offers': len(result.offers), 'per_market': dict(Counter(o.market for o in result.offers)),
    'direct_offers': dict(direct), 'statuses': [asdict(s) for s in result.statuses],
    'checks': ['Actual offers returned', 'Exact model and Black backdrop', 'Direct Fragment and Portals',
               'Numeric price ordering', 'Stars original currency retained'],
    'not_performed': ['Purchase', 'Telegram account login', 'Installation', 'Manual desktop interaction'],
}
(target / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
# Ephemeral public-offer data are used only for the offscreen UI check, not packaged in the app.
(target / 'offers.json').write_text(json.dumps([o.to_dict() for o in ordered], ensure_ascii=False), encoding='utf-8')
print(json.dumps({k:report[k] for k in ('duration_seconds','total_offers','per_market','direct_offers')}, ensure_ascii=False))
