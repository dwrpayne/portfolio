import bisect


def find_le(a, x, default=None):
    i = bisect.bisect_right(a, x)
    if i:
        return a[i - 1]
    if default is not None:
        return default
    raise ValueError


def find_le_index(a, x, default=None):
    i = bisect.bisect_right(a, x)
    if i:
        return i - 1
    if default is not None:
        return default
    raise ValueError


def plotly_iframe_from_url(url):
    if not url:
        return None
    return '<iframe id="igraph" scrolling="no" style="border:none;" seamless="seamless" src="{}?modebar=false&link=false" height="525" width="100%"/></iframe>'.format(
        url)
