"""Bundled translations and CLDR currency names. Never calls a translation service."""
import json
from functools import lru_cache
from pathlib import Path
from PySide6.QtCore import QLocale, Qt, QObject
from PySide6.QtWidgets import QApplication, QWidget

LANGUAGES = {
    'en':'English','ru':'Русский','uk':'Українська','de':'Deutsch','fr':'Français',
    'es':'Español','it':'Italiano','pt_PT':'Português','pt_BR':'Português (Brasil)',
    'pl':'Polski','cs':'Čeština','nl':'Nederlands','sv':'Svenska','tr':'Türkçe',
    'ar':'العربية','he':'עברית','fa':'فارسی','hi':'हिन्दी','bn':'বাংলা','ur':'اردو',
    'id':'Bahasa Indonesia','ms':'Bahasa Melayu','vi':'Tiếng Việt','th':'ไทย',
    'zh_CN':'简体中文','zh_TW':'繁體中文','ja':'日本語','ko':'한국어',
}
EN = {
    'catalog':'Catalog','favorites':'Favorites','searches':'Searches','rates':'Rates',
    'search':'Search','filters':'Filters','stop':'Stop','search_placeholder':'Name or gift link',
    'themes':'Themes','all_themes':'All themes','collapse_themes':'Collapse themes',
    'theme_monochrome':'Monochromes',
    'color':'Color','all_colors':'All colors','err_color':'Unknown monochrome color',
    'color_black':'Black','color_gray':'Gray','color_white':'White','color_brown':'Brown',
    'color_red':'Red','color_orange':'Orange','color_yellow':'Yellow','color_green':'Green',
    'color_teal':'Turquoise','color_blue':'Blue','color_violet':'Violet','color_purple':'Purple','color_pink':'Pink',
    'progress_checked':'Checks: {checked}/{total} · Pages: {pages} · Offers: {offers}',
    'progress_complete':'Search finished',
    'progress_note':'The bar counts completed marketplace checks, including failed checks. The total number of offers is unknown. Source errors and incomplete data are shown separately.',
    'collection':'Collection','model':'Model','backdrop':'Backdrop','symbol':'Symbol',
    'collections':'Collections','models':'Models','price':'Price','from':'From','to':'To',
    'gift_number':'Gift number','reset':'Reset','cancel':'Cancel','apply':'Show',
    'currency_search':'Currency code or name','original':'Original currency','actions':'Actions',
    'save_search':'Save search','export':'Export CSV','sources':'Sources','refresh':'Refresh',
    'sort_low':'Lowest price','sort_high':'Highest price','sort_number':'Gift number',
    'sort_fresh':'Recently updated','sort_rarity':'Model rarity','search_list':'Search this list',
    'search_model':'Find a model','language':'Language','system_language':'System language',
    'no_results':'No matching offers','loading':'Searching…',
    'change_filters':'Try another model, backdrop, theme or price range.',
    'empty_favorites':'Open a gift and add it to favorites.',
    'live_results':'Offers appear as sources respond.','offers':'Offers',
    'offers_count':'Offers: {count}','collections_count':'Collections: {count}',
    'models_count':'Models: {count}','selected_models':'Models: {count}',
    'updating':'Updating…','saved':'Saved','index':'Index','direct':'Direct',
    'open_offer':'Open offer','copy_link':'Copy link','add_favorite':'Add to favorites',
    'remove_favorite':'Remove from favorites','not_specified':'Not specified',
    'source_direct':'Direct marketplace response','source_cached':'Saved offer',
    'source_index':'browse.tg index','unknown_time':'Time unknown',
    'rate_unavailable':'Rate unavailable','unknown':'Unknown','no_data':'No data',
    'rate_title':'Rates and conversion','rate_reference':'Approximate conversion. Stars use the Fragment purchase price. Marketplace fees are not included.',
    'rate_credit':'Currency rates provided by ExchangeRate-API',
    'rate_dates':'Rates: {date}','rate_fiat':'Fiat currencies','rate_stars':'Stars purchase reference',
    'price_note':'Listing price. Marketplace fees may apply.',
    'source_warning':'Some prices are from an index or cache. Check the source and date before opening an offer.',
    'invalid_price':'Check the price range','invalid_number':'Check the gift number',
    'choose_market':'Select a marketplace','search_saved':'Search saved',
    'csv_saved':'Offers exported to CSV','open_search':'Open search',
    'no_searches':'Save a search using the Actions menu.',
    'saved_searches':'Saved searches','no_sources':'No source selected',
    'source_no_offers':'No offers','source_unavailable':'Unavailable','source_partial':'Partial',
    'source_freshness':'Source and date','source_status':'Marketplace status',
    'ago_now':'Just now','ago_min':'{count} min ago','ago_hour':'{count} h ago','ago_day':'{count} d ago',
    'stopped':'Stopped. Loaded offers have been kept.',
    'theme_minecraft':'Minecraft','theme_cheese':'Cheese','theme_watermelon':'Watermelon',
    'theme_strawberry':'Strawberry','theme_pumpkin':'Pumpkins','theme_bee':'Bees and honey',
    'theme_sakura':'Sakura','theme_snowman':'Snowmen','theme_skeleton':'Skeletons','theme_rainbow':'Rainbow',
    'err_auth':'Authentication required','err_denied':'Source refused access',
    'err_limit':'Source rate limit reached','err_http':'Source returned HTTP {code}',
    'err_timeout':'Source did not respond in time','err_connection':'Cannot connect to source',
    'err_response':'Cannot read source response','err_theme':'Theme not found',
    'err_collection':'Collection not found','err_link':'The link refers to a different or unknown collection.',
    'err_number':'The link number does not match the selected number.',
    'err_theme_conflict':'Search and selected theme do not match.',
    'err_collection_conflict':'Search and selected collection do not match.',
    'err_choose':'Select a collection, model or theme.',
    'err_models':'No models match these filters.',
    'catalog_updated':'Catalog updated','catalog_partial':'Catalog updated partially',
    'local_catalog':'Local catalog','background_catalog':'Catalog: {count}/{total}',
    'loading_offers':'Loaded: {count}','more_pages':'Loading more pages…',
    'scope_models':'{collections} collections · {models} models',
    'search_term':'Search: {text}','data_incomplete':'Some source data could not be read; results are incomplete.',
    'index_note':'Public index. Check price and availability on the marketplace.',
    'index_updating':'The index is updating. Search again later.',
    'index_limited':'The index limited results. Narrow the model or backdrop.',
    'no_collection_source':'Collection not available on this marketplace.',
    'no_fresh_source':'No fresh response','partial_source':'Part of the source results',
    'one_page':'One page loaded','fees_excluded':'Marketplace fees are not included.',
    'source_repeat':'The source repeated a page cursor; results are incomplete.',
    'rates_error':'A rate source is unavailable','stars_unavailable':'Public Stars price is unavailable.',
    'fiat_unavailable':'Currency rates are unavailable.','gram_unavailable':'GRAM rate is unavailable.',
    'currency':'Currency','number':'Number','market':'Marketplace','native_price':'Original price',
    'native_currency':'Original currency','converted_price':'Approximate price','converted_currency':'Display currency',
    'source':'Source','source_time':'Source time','link':'Link','yes':'Yes','no':'No',
}
_root=Path(__file__).parent/'locales'
_language='ru'
_requested='system'

@lru_cache(maxsize=32)
def translations(code):
    try:return json.loads((_root/(code+'.json')).read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}

def resolve_language(value='system', system=None):
    if value=='system':
        preferred=QLocale.system().uiLanguages()
        value=system if system is not None else preferred[0] if preferred else QLocale.system().name()
    value=str(value or 'en').replace('-','_')
    if value in LANGUAGES:return value
    if value.startswith('zh'):
        return 'zh_TW' if any(x in value for x in ('TW','HK','Hant','MO')) else 'zh_CN'
    if value.startswith('pt'):return 'pt_BR' if 'BR' in value else 'pt_PT'
    return value.split('_')[0] if value.split('_')[0] in LANGUAGES else 'en'

def set_language(value='system'):
    global _language,_requested
    _requested=value;_language=resolve_language(value)
    QLocale.setDefault(QLocale(_language))
    app=QApplication.instance()
    if app:app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if _language in ('ar','he','fa','ur') else Qt.LayoutDirection.LeftToRight)
    return _language

def language_code():return _language
def requested_language():return _requested

def tr(key,**values):
    result=translations(_language).get(key,EN.get(key,key)) if _language!='en' else EN.get(key,key)
    return result.format(**values) if values else result

def bind(widget,key,method='setText',**values):
    bindings=getattr(widget,'_translations',{})
    bindings[method]=(key,values);widget._translations=bindings
    getattr(widget,method)(tr(key,**values));return widget

def refresh_tree(root):
    for widget in [root]+root.findChildren(QObject):
        for method,(key,values) in getattr(widget,'_translations',{}).items():
            getattr(widget,method)(tr(key,**values))
        if hasattr(widget,'updateGeometry'):widget.updateGeometry()

def theme_name(key):return tr('theme_'+key)

@lru_cache(maxsize=1)
def _currencies():
    return json.loads((_root/'currencies.json').read_text(encoding='utf-8'))

def currency_name(code,language=None):
    if code in ('GRAM','Stars'):return code
    if code=='ORIGINAL':return tr('original')
    return _currencies().get(language or _language,{}).get(code,code)

def format_number(value,digits=2):
    # Decimal is formatted first, so large values are never rounded via float.
    from decimal import Decimal
    text=f'{value:,.{digits}f}'
    if digits:text=text.rstrip('0').rstrip('.')
    locale=QLocale(_language);group=locale.groupSeparator();decimal=locale.decimalPoint()
    whole,_,fraction=text.partition('.')
    return whole.replace(',',group)+(decimal+fraction if fraction else '')

def age_text(value):
    import time
    if not value:return tr('unknown_time')
    age=max(0,time.time()-value)
    if age<60:return tr('ago_now')
    return tr('ago_min',count=int(age/60)) if age<3600 else tr('ago_hour',count=int(age/3600)) if age<86400 else tr('ago_day',count=int(age/86400))

def message(text):
    """Translate source notes from older profiles without rewriting saved data."""
    replacements={
        'Сохранённые предложения. Обновление выполняется в фоне.':tr('source_cached')+' · '+tr('updating'),
        'Публичный агрегатор; цена и наличие требуют проверки на площадке.':tr('index_note'),
        'Комиссии не добавлены.':tr('fees_excluded'),
        'Прямой ответ Portals.':tr('source_direct')+' · Portals.',
        'Прямой ответ Fragment.':tr('source_direct')+' · Fragment.',
        'Источник вернул часть предложений.':tr('partial_source'),
        'Агрегатор обновляет данные; нажмите «Найти» позже.':tr('index_updating'),
        'Загружена одна страница.':tr('one_page'),
    }
    for code in LANGUAGES:
        pack=translations(code) if code!='en' else EN
        for key,value in pack.items():
            if key not in ('price_note','fees_excluded') and not key.startswith(('err_','index_','source_','data_','partial_','no_collection','rates_')):continue
            if len(value)>=10 and '{' not in value:replacements[value]=tr(key)
    for old,new in sorted(replacements.items(),key=lambda pair:len(pair[0]),reverse=True):text=text.replace(old,new)
    return text
