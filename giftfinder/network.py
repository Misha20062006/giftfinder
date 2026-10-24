from .i18n import tr, theme_name
import requests

USER_AGENT = 'GiftFinder/0.6 (Windows; read-only gift search)'
TIMEOUT = (8, 22)


def request(method, url, session=None, **kwargs):
    response = (session or requests).request(method, url, timeout=TIMEOUT,
        headers={'User-Agent': USER_AGENT, 'Accept': 'application/json,text/html'}, **kwargs)
    response.raise_for_status()
    return response


def error_note(error):
    if isinstance(error, requests.HTTPError):
        code = error.response.status_code
        return {401: tr('err_auth'), 403: tr('err_denied'),
                429: tr('err_limit')}.get(code, tr('err_http',code=code))
    if isinstance(error, requests.Timeout):
        return tr('err_timeout')
    if isinstance(error, requests.ConnectionError):
        return tr('err_connection')
    return tr('err_response')
