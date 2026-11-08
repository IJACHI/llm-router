from billing.totals import calc_total

def summary(orders):
    return [calc_total(o) for o in orders]
