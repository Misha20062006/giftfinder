from __future__ import annotations

import concurrent.futures
import json
import re
import time
from decimal import Decimal
from pathlib import Path

from bs4 import BeautifulSoup

from .core import number, fmt
from .i18n import tr, format_number
from .network import request

NAMES = {'RUB':'Российский рубль', 'USD':'Доллар США', 'EUR':'Евро', 'GBP':'Британский фунт',
         'CNY':'Китайский юань', 'JPY':'Японская иена', 'TRY':'Турецкая лира', 'AMD':'Армянский драм',
         'KZT':'Казахстанский тенге', 'UAH':'Украинская гривна', 'BYN':'Белорусский рубль',
         'GEL':'Грузинский лари', 'AED':'Дирхам ОАЭ', 'INR':'Индийская рупия', 'CHF':'Швейцарский франк',
         'CAD':'Канадский доллар', 'AUD':'Австралийский доллар', 'BRL':'Бразильский реал', 'KRW':'Южнокорейская вона',
         'PLN':'Польский злотый', 'SEK':'Шведская крона', 'THB':'Тайский бат', 'VND':'Вьетнамский донг'}
SYMBOLS = {'RUB':'₽','USD':'$','EUR':'€','GBP':'£','JPY':'¥','CNY':'¥'}


def parse_stars_price(html):
    soup = BeautifulSoup(html, 'html.parser')
    packages = []
    for row in soup.select('.js-stars-options .tm-form-radio-item'):
        field, usd = row.select_one('input[name="stars"]'), row.select_one('.icon-usd')
        quantity = number(field.get('value')) if field else None
        amount = number(usd.get_text('',strip=True)) if usd else None
        if quantity and amount:
            packages.append((quantity,amount))
    if not packages:
        raise ValueError(tr('stars_unavailable'))
    # The published 1000-Star package avoids the rounding of small packages.
    quantity, amount = next((x for x in packages if x[0] == 1000), max(packages))
    match = re.search(r'"tonRate"\s*:\s*([\d.]+)', html)
    return {'star_usd':str(amount/quantity), 'star_source':'Fragment · цена покупки пакета '+str(quantity)+' Stars',
            'star_updated':time.time(), 'fragment_gram_usd':str(number(match[1])) if match else None}


class RateBook:
    def __init__(self, directory):
        self.path = Path(directory)/'exchange-rates.json'
        self.data = {'fx': {'USD':'1'}, 'gram_usd':None, 'star_usd':None}
        self.error = ''
        for path in (Path(__file__).parent/'rates_seed.json', self.path):
            try:
                value = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(value,dict):
                    self.data.update(value)
            except (OSError,ValueError):
                pass

    def refresh(self):
        updates = {}
        errors = []
        def fx():
            payload = request('GET','https://open.er-api.com/v6/latest/USD').json()
            if payload.get('result') != 'success' or not payload.get('rates',{}).get('RUB'):
                raise ValueError(tr('fiat_unavailable'))
            return {'fx':{c:str(v) for c,v in payload['rates'].items() if number(v)},
                    'fx_updated':payload.get('time_last_update_unix'), 'fx_source':'ExchangeRate-API'}
        def coin():
            payload = request('GET','https://api.coingecko.com/api/v3/simple/price',
                              params={'ids':'the-open-network','vs_currencies':'usd','include_last_updated_at':'true'}).json()['the-open-network']
            if not number(payload.get('usd')) or not payload.get('last_updated_at'):
                raise ValueError(tr('gram_unavailable'))
            return {'gram_usd':str(payload['usd']), 'gram_updated':payload['last_updated_at'], 'gram_source':'CoinGecko'}
        def stars():
            return parse_stars_price(request('GET','https://fragment.com/stars/buy').text)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [pool.submit(fn) for fn in (fx,coin,stars)]
            for job in jobs:
                try:
                    updates.update(job.result())
                except Exception:
                    errors.append(tr('rates_error'))
        if 'gram_usd' not in updates and updates.get('fragment_gram_usd'):
            updates.update(gram_usd=updates['fragment_gram_usd'],gram_updated=updates['star_updated'],gram_source='Fragment')
        self.data = {**self.data, **updates, 'retrieved_at':time.time()}
        self.error = '; '.join(dict.fromkeys(errors))
        if updates:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.data,ensure_ascii=False,indent=2),encoding='utf-8')
            tmp.replace(self.path)
        return self.data

    def currencies(self):
        return sorted(self.data.get('fx', {}))

    def usd(self, offer):
        if offer.amount is None:
            return None
        if offer.currency in ('TON','GRAM'):
            rate = number(self.data.get('gram_usd'))
        elif offer.currency == 'Stars':
            rate = number(self.data.get('star_usd'))
        else:
            rate = None
        return offer.amount*rate if rate else None

    def convert(self, offer, currency):
        if currency == 'ORIGINAL':
            return offer.amount
        usd = self.usd(offer)
        if currency == 'GRAM':
            rate = number(self.data.get('gram_usd'))
            return usd/rate if usd is not None and rate else None
        if currency == 'Stars':
            rate = number(self.data.get('star_usd'))
            return usd/rate if usd is not None and rate else None
        rate = number(self.data.get('fx', {}).get(currency))
        return usd*rate if usd is not None and rate else None

    def display(self, offer, currency):
        if currency == 'ORIGINAL':
            return offer.price_label
        amount = self.convert(offer,currency)
        return ('≈ '+format_number(amount)+' '+SYMBOLS.get(currency,currency)) if amount is not None else tr('rate_unavailable')

    def note(self):
        times = [self.data.get(key) for key in ('fx_updated','gram_updated','star_updated')]
        valid = [t for t in times if isinstance(t,(int,float)) and t>0]
        updated = time.strftime('%d.%m %H:%M UTC',time.gmtime(min(valid))) if valid else tr('no_data')
        return tr('rate_dates',date=updated)

    def details(self):
        def date(key):
            value=self.data.get(key)
            return time.strftime('%Y-%m-%d %H:%M UTC',time.gmtime(value)) if value else tr('unknown')
        return (f'GRAM: {self.data.get("gram_source","—")} · {date("gram_updated")}\n'
                f'{tr("rate_fiat")}: ExchangeRate-API · {date("fx_updated")}\n'
                f'Stars: Fragment · {tr("rate_stars")} · {date("star_updated")}\n'
                +tr('rate_reference')+'\nhttps://www.exchangerate-api.com')
