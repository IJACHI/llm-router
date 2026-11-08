from billing.totals import calc_total

def invoice_total(invoice):
    return calc_total(invoice["items"]) + invoice.get("shipping", 0)
