from logistics.rates import HEAVY_RATE, HEAVY_THRESHOLD_KG, LIGHT_RATE


def shipping_cost(weight_kg):
    rate = HEAVY_RATE if weight_kg > HEAVY_THRESHOLD_KG else LIGHT_RATE
    return round(weight_kg * rate, 2)
