import bisect

def find_le(a,x, default=None):
    i = bisect.bisect_right(a,x)
    if i:
        return a[i-1]
    if default is not None:
        return default
    raise ValueError

def find_le_index(a,x, default=None):
    i = bisect.bisect_right(a,x)
    if i:
        return i-1
    if default is not None:
        return default
    raise ValueError

