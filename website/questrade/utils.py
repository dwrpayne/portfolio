def as_currency(amt):
    return "{}${:,.2f}".format(["","-"][amt<0], abs(amt))

def strdate(arrow_date):
    return arrow_date.strftime('%Y-%m-%d')

