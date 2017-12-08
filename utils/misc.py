import bisect

def find_le(a,x):
    i = bisect.bisect_right(a,x)
    if i:
        return a[i-1]
    raise ValueError
