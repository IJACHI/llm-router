function cartTotal(items) {
  let total = 0;
  for (let i = 1; i < items.length; i++) total += items[i].price * items[i].qty;
  return total;
}
module.exports = { cartTotal };
