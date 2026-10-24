"""Build bundled UI packs and CLDR currency names (Babel, build time only)."""
import ast,json
from pathlib import Path
from babel.numbers import get_currency_name,get_currency_symbol
root=Path(__file__).resolve().parents[1]/'giftfinder'
tree=ast.parse((root/'i18n.py').read_text(encoding='utf-8'))
values={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('EN','LANGUAGES')}
packs={code:{} for code in values['LANGUAGES']};packs['en']=dict(values['EN'])
for path in sorted((Path(__file__).resolve().parents[1]/'translations').glob('*.txt')):
    lines=path.read_text(encoding='utf-8').splitlines();keys=lines[0].split('|')
    for line in lines[1:]:
        if not line.strip():continue
        code,*texts=line.split('|');assert len(texts)==len(keys),(path.name,code,len(texts),len(keys))
        packs[code].update(dict(zip(keys,texts)))
target=root/'locales';target.mkdir(exist_ok=True)
for code,pack in packs.items():
    if code=='en':continue
    for key,source in {'offers_count':'offers','collections_count':'collections','models_count':'models','selected_models':'models'}.items():pack[key]=pack[source]+': {count}'
    pack.update({'rate_dates':pack['rates']+': {date}','scope_models':pack['collections']+': {collections} · '+pack['models']+': {models}',
        'search_term':pack['search']+': {text}','background_catalog':pack['catalog']+': {count}/{total}',
        'loading_offers':pack['offers']+': {count}','saved_searches':pack['searches'],'source_status':pack['sources'],
        'number':pack['gift_number'],'native_price':pack['original']+' · '+pack['price'],'native_currency':pack['original'],
        'converted_price':'≈ '+pack['price'],'converted_currency':pack['currency']})
for code,pack in packs.items():
    if code=='ru':pack['err_link']='Ссылка относится к другой коллекции или её нет в каталоге.'
    (target/(code+'.json')).write_text(json.dumps(pack,ensure_ascii=False,indent=2),encoding='utf-8')
codes=list(json.loads((root/'rates_seed.json').read_text(encoding='utf-8'))['fx'])
currencies={locale:{code:get_currency_name(code,locale=locale) for code in codes} for locale in packs}
(target/'currencies.json').write_text(json.dumps(currencies,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
symbols={code:get_currency_symbol(code,locale='en') for code in codes}
symbols.update({'RUB':'₽','EUR':'€','USD':'$','JPY':'¥','CNY':'¥','GBP':'£','INR':'₹','KRW':'₩','TRY':'₺','UAH':'₴','KZT':'₸','GEL':'₾','AMD':'֏','ILS':'₪','THB':'฿','VND':'₫','PHP':'₱','NGN':'₦','BRL':'R$','PLN':'zł','BYN':'Br','CHF':'Fr','IDR':'Rp','MYR':'RM'})
(target/'currency-symbols.json').write_text(json.dumps(symbols,ensure_ascii=False),encoding='utf-8')
print(json.dumps({c:{'translated':len(p),'missing':len(set(values['EN'])-set(p))} for c,p in packs.items()}))
